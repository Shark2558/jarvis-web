// android/app/src/main/java/io/github/shark2558/jarvis/calls/CallsAccess.kt
// R18 D: the phone permissions JARVIS's calls need, and what the app tells the cloud it may do.
//
//   CALL_PHONE           place the call he approved (TelecomManager.placeCall)
//   ANSWER_PHONE_CALLS   answer a ringing call (acceptRingingCall) and end JARVIS's call (endCall)
//   READ_PHONE_STATE     hear the PHONE_STATE broadcast: ringing, off the hook, idle
//   READ_CALL_LOG        ONLY for answering missed calls with a "saved contacts" rule. Since
//                        Android 9 the PHONE_STATE broadcast carries the caller's number
//                        (EXTRA_INCOMING_NUMBER) only to an app that holds READ_CALL_LOG as well
//                        as READ_PHONE_STATE, and Android 16 still has no other way for an app that
//                        is neither the dialer nor the call screener to learn who is ringing (a
//                        CallScreeningService would need him to make JARVIS his caller-ID app,
//                        taking that place from the one he uses). So it is asked separately, only
//                        when he chooses it, and the number leaves the phone only while answering
//                        is on and the cloud's answer asks for it. JARVIS never reads the call log
//                        itself.
package io.github.shark2558.jarvis.calls

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import androidx.core.app.NotificationManagerCompat
import io.github.shark2558.jarvis.core.CallCan

object CallsAccess {
    val CORE: Array<String> = arrayOf(
        Manifest.permission.CALL_PHONE,
        Manifest.permission.ANSWER_PHONE_CALLS,
        Manifest.permission.READ_PHONE_STATE,
    )
    const val NUMBER: String = Manifest.permission.READ_CALL_LOG

    fun granted(context: Context, permission: String): Boolean =
        context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED

    fun coreGranted(context: Context): Boolean = CORE.all { granted(context, it) }

    fun can(context: Context): CallCan = CallCan(
        place = granted(context, Manifest.permission.CALL_PHONE),
        answer = granted(context, Manifest.permission.ANSWER_PHONE_CALLS),
        state = granted(context, Manifest.permission.READ_PHONE_STATE),
        number = granted(context, NUMBER) && granted(context, Manifest.permission.READ_PHONE_STATE),
        notify = NotificationManagerCompat.from(context).areNotificationsEnabled(),
    )
}
