// android/app/src/main/java/io/github/shark2558/jarvis/calls/CallsStore.kt
// R18 D: the little the calls part remembers, in its own private preferences (never backed up:
// the app allows no backup at all). The cloud's command key (public; it only verifies), what the
// last door answer said about answering missed calls, the call machine's one line (a caller's
// number only while the phone rings), the events not yet taken, the commands acted on (by id,
// until they expire) and the ids to acknowledge. Every read-modify-write holds LOCK: the
// call-state receiver, the notification service and a tapped notification may run at once.
package io.github.shark2558.jarvis.calls

import android.content.Context
import android.content.SharedPreferences
import io.github.shark2558.jarvis.core.CallEvent
import io.github.shark2558.jarvis.core.CallMachine
import io.github.shark2558.jarvis.core.CallPayloads
import io.github.shark2558.jarvis.core.CallWire
import io.github.shark2558.jarvis.core.CallsAnswer

data class AnsweringNow(val on: Boolean, val afterRings: Int, val sendNumber: Boolean)

class CallsStore(context: Context) {
    private val prefs: SharedPreferences =
        context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun key(): String? = prefs.getString(KEY, null)?.takeIf { CallWire.isKey(it) }

    fun answering(): AnsweringNow = AnsweringNow(
        on = prefs.getBoolean(ANSWER_ON, false),
        afterRings = prefs.getInt(ANSWER_RINGS, DEFAULT_RINGS),
        sendNumber = prefs.getBoolean(ANSWER_NUMBER, false),
    )

    fun saveAnswer(answer: CallsAnswer) {
        prefs.edit()
            .putString(KEY, answer.key)
            .putBoolean(ANSWER_ON, answer.answeringOn)
            .putInt(ANSWER_RINGS, answer.afterRings)
            .putBoolean(ANSWER_NUMBER, answer.sendNumber)
            .commit()
    }

    fun machine(): CallMachine = CallMachine.decode(prefs.getString(MACHINE, null))

    fun saveMachine(machine: CallMachine) {
        prefs.edit().putString(MACHINE, machine.encode()).commit()
    }

    /** Events not yet taken by the cloud, oldest first (at most QUEUE_MAX: the oldest go). */
    fun queued(): List<CallEvent> = lines(QUEUE).mapNotNull { CallPayloads.decode(it) }

    fun queue(events: List<CallEvent>) {
        if (events.isEmpty()) return
        val all = lines(QUEUE) + events.map { CallPayloads.encode(it) }
        putLines(QUEUE, all.distinct().takeLast(QUEUE_MAX))
    }

    fun drop(ids: Set<String>) {
        if (ids.isEmpty()) return
        putLines(QUEUE, lines(QUEUE).filter { line -> CallPayloads.decode(line)?.id !in ids })
    }

    /** A command acted on (or offered to him as a notification) is never acted on again. */
    fun acted(id: String): Boolean = lines(ACTED).any { it.substringBefore(':') == id }

    fun markActed(id: String, exp: Long, nowS: Long) {
        val kept = lines(ACTED).filter { (it.substringAfter(':').toLongOrNull() ?: 0L) + ACTED_MARGIN_S > nowS }
        putLines(ACTED, (kept + "$id:$exp").takeLast(ACTED_MAX))
    }

    fun acks(): List<String> = lines(ACKS).filter { CallWire.COMMAND_ID.matches(it) }

    fun addAck(id: String) {
        if (CallWire.COMMAND_ID.matches(id)) putLines(ACKS, (acks() + id).distinct().takeLast(CallWire.MAX_ACKS))
    }

    fun clearAcks(ids: List<String>) {
        putLines(ACKS, acks().filter { it !in ids })
    }

    /** True once the app set the call's sound device itself (cleared when the call ends). */
    fun routed(): Boolean = prefs.getBoolean(ROUTED, false)

    fun setRouted(routed: Boolean) {
        prefs.edit().putBoolean(ROUTED, routed).apply()
    }

    private fun lines(name: String): List<String> =
        prefs.getString(name, null).orEmpty().lineSequence().map { it.trim() }.filter { it.isNotEmpty() }.toList()

    private fun putLines(name: String, items: List<String>) {
        prefs.edit().putString(name, items.joinToString("\n")).commit()
    }

    companion object {
        /** Held around every read-modify-write of this store. */
        val LOCK = Any()
        private const val FILE = "jarvis_calls"
        private const val KEY = "cloud_key"
        private const val ANSWER_ON = "answering_on"
        private const val ANSWER_RINGS = "answering_rings"
        private const val ANSWER_NUMBER = "answering_number"
        private const val MACHINE = "machine"
        private const val QUEUE = "events"
        private const val ACTED = "acted"
        private const val ACKS = "acks"
        private const val ROUTED = "routed"
        private const val DEFAULT_RINGS = 5
        private const val QUEUE_MAX = 32
        private const val ACTED_MAX = 200
        private const val ACTED_MARGIN_S = 900L
    }
}
