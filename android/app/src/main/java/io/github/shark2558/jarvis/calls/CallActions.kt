// android/app/src/main/java/io/github/shark2558/jarvis/calls/CallActions.kt
// R18 D: what the phone does with a command that passed every check of core's CallCommands (the
// cloud's signature, this phone, its time, never acted on before). Each is acted on once and
// reported back as a call.result.
//
//   call.dial    placed with TelecomManager.placeCall (the system's own call screen opens, as for
//                any call) only while the command is fresh and he gave the permission. If Android
//                does not start it (a call placed from the background can be held back), or the
//                command is no longer fresh, a high-priority notification "Tap to let JARVIS call
//                <name>" places it on his tap instead (CallTapActivity checks it again).
//   call.answer  TelecomManager.acceptRingingCall, only while the phone rings.
//   call.end     TelecomManager.endCall, only for the call JARVIS placed or answered: never his own.
//   call.route   moves the call's sound between Bluetooth and the earpiece where Android lets an
//                app ask (AudioManager.setCommunicationDevice, Android 12 and newer). Android gives
//                the phone call's own route to the dialer, so this may not take: the result says so
//                and the console tells him to tap "Phone" on the call screen.
//   call.card    a notification with Approve and Decline (CallNotices.card).
package io.github.shark2558.jarvis.calls

import android.Manifest
import android.annotation.SuppressLint
import android.annotation.TargetApi
import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.telecom.TelecomManager
import android.util.Log
import io.github.shark2558.jarvis.core.AnswerCommand
import io.github.shark2558.jarvis.core.CallCommand
import io.github.shark2558.jarvis.core.CallCommands
import io.github.shark2558.jarvis.core.CallEvent
import io.github.shark2558.jarvis.core.CallPayloads
import io.github.shark2558.jarvis.core.CallsAnswer
import io.github.shark2558.jarvis.core.CardCommand
import io.github.shark2558.jarvis.core.CommandVerdict
import io.github.shark2558.jarvis.core.DialCommand
import io.github.shark2558.jarvis.core.EndCommand
import io.github.shark2558.jarvis.core.PhonePhase
import io.github.shark2558.jarvis.core.ResultEvent
import io.github.shark2558.jarvis.core.RouteCommand
import io.github.shark2558.jarvis.link.AppState

object CallActions {
    private const val TAG = "JarvisCalls"

    /** How long Android has to take the call off the hook before he is asked to tap. */
    private const val DIAL_CONFIRM_MS = 8_000L
    private const val POLL_MS = 250L
    private const val ROUTE_SETTLE_MS = 500L

    /** Every good command in the answer, acted on once; the results to report. */
    fun actOn(context: Context, answer: CallsAnswer): List<CallEvent> {
        val device = AppState(context).deviceId() ?: return emptyList()
        val store = CallsStore(context)
        val out = ArrayList<CallEvent>()
        for ((body, sig) in answer.commands) {
            val now = CallsLink.nowS()
            val checked = synchronized(CallsStore.LOCK) {
                val c = CallCommands.check(answer.key, body, sig, device, now) { store.acted(it) }
                val cmd = c.command
                if (cmd != null) {
                    store.markActed(cmd.head.id, cmd.head.exp, now)
                    store.addAck(cmd.head.id)
                } else if (c.verdict == CommandVerdict.SEEN || c.verdict == CommandVerdict.EXPIRED) {
                    CallCommands.read(body)?.let { store.addAck(it.head.id) } // signed and ours: done
                }
                c
            }
            val cmd = checked.command
            if (cmd == null) {
                Log.i(TAG, "a call command was not acted on: ${checked.verdict.code}")
                continue
            }
            out.addAll(act(context, cmd, body, sig, now))
        }
        return out
    }

    private fun act(context: Context, cmd: CallCommand, body: String, sig: String, now: Long): List<CallEvent> = when (cmd) {
        is DialCommand -> listOf(dial(context, cmd, body, sig, now))
        is AnswerCommand -> listOf(answer(context, cmd))
        is EndCommand -> listOf(end(context, cmd))
        is RouteCommand -> listOf(route(context, cmd))
        is CardCommand -> {
            CallNotices.card(context, cmd, body, sig, now)
            emptyList()
        }
    }

    fun result(cmd: CallCommand, ok: Boolean, code: String): ResultEvent {
        val callId = when (cmd) {
            is DialCommand -> cmd.callId
            is AnswerCommand -> cmd.callId
            is EndCommand -> cmd.callId
            is RouteCommand -> cmd.callId
            is CardCommand -> null
        }
        return ResultEvent(CallPayloads.newEventId(), cmd.head.id, callId, cmd.head.type, ok, code, CallsLink.nowS())
    }

    // ---- call.dial ----------------------------------------------------------------------------
    private fun dial(context: Context, cmd: DialCommand, body: String, sig: String, now: Long): ResultEvent {
        if (!CallsAccess.granted(context, Manifest.permission.CALL_PHONE)) {
            CallNotices.needsPermission(context)
            return result(cmd, false, "no_permission")
        }
        if (!CallCommands.autoDial(cmd, now) || !place(context, cmd) || !offHookSoon(context, cmd.callId)) {
            CallNotices.dialTap(context, cmd, body, sig, now)
            return result(cmd, false, "needs_tap")
        }
        return result(cmd, true, "placed")
    }

    /** Places the call (the system's own call screen opens); false when Android refused it. */
    @SuppressLint("MissingPermission") // CALL_PHONE is checked by every caller first
    fun place(context: Context, cmd: DialCommand): Boolean {
        if (!CallsAccess.granted(context, Manifest.permission.CALL_PHONE)) return false
        val telecom = context.getSystemService(TelecomManager::class.java) ?: return false
        val store = CallsStore(context)
        synchronized(CallsStore.LOCK) {
            val machine = store.machine()
            if (machine.phase == PhonePhase.OFFHOOK && machine.callId == cmd.callId) return true // already on
            store.saveMachine(machine.dialPlaced(cmd.callId, System.currentTimeMillis()))
        }
        return try {
            telecom.placeCall(Uri.fromParts("tel", cmd.number, null), Bundle())
            true
        } catch (e: SecurityException) {
            Log.w(TAG, "the call was not placed: ${e.javaClass.simpleName}")
            false
        }
    }

    private fun offHookSoon(context: Context, callId: String): Boolean {
        val store = CallsStore(context)
        val until = System.currentTimeMillis() + DIAL_CONFIRM_MS
        while (System.currentTimeMillis() < until) {
            val m = synchronized(CallsStore.LOCK) { store.machine() }
            if (m.phase == PhonePhase.OFFHOOK && m.callId == callId) return true
            Thread.sleep(POLL_MS)
        }
        return false
    }

    // ---- call.answer and call.end -------------------------------------------------------------
    @SuppressLint("MissingPermission") // ANSWER_PHONE_CALLS is checked on the first line
    @Suppress("DEPRECATION") // acceptRingingCall: still the one call an app with this permission has
    private fun answer(context: Context, cmd: AnswerCommand): ResultEvent {
        if (!CallsAccess.granted(context, Manifest.permission.ANSWER_PHONE_CALLS)) return result(cmd, false, "no_permission")
        val telecom = context.getSystemService(TelecomManager::class.java) ?: return result(cmd, false, "refused")
        val store = CallsStore(context)
        synchronized(CallsStore.LOCK) {
            val machine = store.machine()
            if (!machine.ringing) return result(cmd, false, "not_ringing")
            store.saveMachine(machine.answered(cmd.callId))
        }
        return try {
            telecom.acceptRingingCall()
            result(cmd, true, "answered")
        } catch (e: SecurityException) {
            result(cmd, false, "no_permission")
        }
    }

    @SuppressLint("MissingPermission") // ANSWER_PHONE_CALLS is checked first
    @Suppress("DEPRECATION") // endCall: still the one call an app with this permission has
    private fun end(context: Context, cmd: EndCommand): ResultEvent {
        val machine = synchronized(CallsStore.LOCK) { CallsStore(context).machine() }
        if (machine.phase == PhonePhase.IDLE) return result(cmd, true, "not_in_call")
        if (machine.callId != cmd.callId) return result(cmd, false, "not_jarvis_call")
        if (!CallsAccess.granted(context, Manifest.permission.ANSWER_PHONE_CALLS)) return result(cmd, false, "no_permission")
        val telecom = context.getSystemService(TelecomManager::class.java) ?: return result(cmd, false, "refused")
        val ended = try {
            telecom.endCall()
        } catch (e: SecurityException) {
            false
        }
        return result(cmd, ended, if (ended) "ended" else "refused")
    }

    // ---- call.route ---------------------------------------------------------------------------
    private fun route(context: Context, cmd: RouteCommand): ResultEvent {
        val machine = synchronized(CallsStore.LOCK) { CallsStore(context).machine() }
        if (machine.phase != PhonePhase.OFFHOOK || machine.callId != cmd.callId) return result(cmd, false, "not_jarvis_call")
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return result(cmd, false, "route_unsupported")
        val moved = moveSound(context, cmd.to)
        if (moved) CallsStore(context).setRouted(true)
        return result(cmd, moved, if (moved) "routed" else "route_refused")
    }

    @TargetApi(Build.VERSION_CODES.S) // route() calls it only on Android 12 and newer
    private fun moveSound(context: Context, to: String): Boolean {
        val audio = context.getSystemService(AudioManager::class.java) ?: return false
        val wanted = if (to == "phone") {
            setOf(AudioDeviceInfo.TYPE_BUILTIN_EARPIECE)
        } else {
            setOf(AudioDeviceInfo.TYPE_BLUETOOTH_SCO, AudioDeviceInfo.TYPE_BLE_HEADSET)
        }
        val device = audio.availableCommunicationDevices.firstOrNull { it.type in wanted } ?: return false
        if (!audio.setCommunicationDevice(device)) return false
        Thread.sleep(ROUTE_SETTLE_MS)
        val now = audio.communicationDevice?.type ?: return false // what the call really uses now
        return now in wanted
    }

    /** When JARVIS's call ends: give the sound back to Android's own choice. */
    fun releaseSound(context: Context) {
        val store = CallsStore(context)
        if (!store.routed()) return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            context.getSystemService(AudioManager::class.java)?.clearCommunicationDevice()
        }
        store.setRouted(false)
    }
}
