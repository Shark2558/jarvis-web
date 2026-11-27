// android/app/src/main/java/io/github/shark2558/jarvis/calls/CallNotices.kt
// R18 D: the calls part's own notifications, on their own high-importance channel "Calls" (so he
// sets its sound once in Android). Each carries the signed command it is about, and the screen a
// tap opens checks that command again before anything happens. A number is never shown: only the
// card's name. On the lock screen each shows only "JARVIS has a call for you".
//
//   dialTap          "Tap to let JARVIS call <name>": Android held a dial back, or it was no longer
//                    fresh; one tap places it (until the approval runs out)
//   card             Approve / Decline for a call card. Approve asks him to unlock first; a card
//                    whose number was never called opens the console for his passkey instead
//   passkey          the cloud wants his passkey for an approved card: opens the Calls panel
//   needsPermission  "Allow JARVIS to place calls": opens the calls set-up screen
package io.github.shark2558.jarvis.calls

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationManagerCompat
import io.github.shark2558.jarvis.R
import io.github.shark2558.jarvis.core.CardCommand
import io.github.shark2558.jarvis.core.DialCommand

object CallNotices {
    const val CHANNEL = "jarvis_calls"
    const val TAG_DIAL = "jarvis_call_dial"
    const val TAG_CARD = "jarvis_call_card"
    private const val TAG_PERMISSION = "jarvis_call_permission"
    private const val MILLIS = 1000L
    private const val FLAGS = PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT

    fun ensure(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        val channel = NotificationChannel(CHANNEL, context.getString(R.string.channel_calls), NotificationManager.IMPORTANCE_HIGH)
        channel.description = context.getString(R.string.channel_calls_about)
        manager.createNotificationChannel(channel)
    }

    fun idFor(subject: String): Int = subject.hashCode()

    fun dialTap(context: Context, cmd: DialCommand, body: String, sig: String, nowS: Long) {
        val name = cmd.label.ifBlank { context.getString(R.string.calls_the_number) }
        val tap = PendingIntent.getActivity(context, idFor(cmd.head.id), CallTapActivity.dial(context, body, sig), FLAGS)
        val builder = base(context, (cmd.head.exp - nowS) * MILLIS)
            .setContentTitle(context.getString(R.string.calls_tap_title, name))
            .setContentText(context.getString(R.string.calls_tap_body))
            .setCategory(Notification.CATEGORY_CALL)
            .setContentIntent(tap)
            .setAutoCancel(true)
        post(context, TAG_DIAL, idFor(cmd.callId), builder.build())
    }

    fun card(context: Context, cmd: CardCommand, body: String, sig: String, nowS: Long) {
        val approve = PendingIntent.getActivity(context, idFor(cmd.head.id), CallTapActivity.approve(context, body, sig), FLAGS)
        val decline = PendingIntent.getBroadcast(context, idFor(cmd.head.id), CallDecisionReceiver.decline(context, body, sig), FLAGS)
        val text = if (cmd.passkey) context.getString(R.string.calls_card_passkey, cmd.purpose) else cmd.purpose
        val approveAction = Notification.Action.Builder(null, context.getString(R.string.calls_approve), approve)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) approveAction.setAuthenticationRequired(true)
        val builder = base(context, (cmd.head.exp - nowS) * MILLIS)
            .setContentTitle(context.getString(R.string.calls_card_title, cmd.label))
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setCategory(Notification.CATEGORY_REMINDER)
            .setContentIntent(approve)
            .addAction(approveAction.build())
            .addAction(Notification.Action.Builder(null, context.getString(R.string.calls_decline), decline).build())
        post(context, TAG_CARD, idFor(cmd.cardId), builder.build())
    }

    /** The cloud wants his passkey for this card: one tap opens the console's Calls panel. */
    fun passkey(context: Context, cmd: CardCommand) {
        val open = PendingIntent.getActivity(context, idFor(cmd.cardId), Intent(context, CallsLauncherActivity::class.java), FLAGS)
        val builder = base(context, 0L)
            .setContentTitle(context.getString(R.string.calls_card_title, cmd.label))
            .setContentText(context.getString(R.string.calls_passkey_body))
            .setContentIntent(open)
            .setAutoCancel(true)
        post(context, TAG_CARD, idFor(cmd.cardId), builder.build())
    }

    fun needsPermission(context: Context) {
        val open = PendingIntent.getActivity(context, 0, Intent(context, CallsSetupActivity::class.java), FLAGS)
        val builder = base(context, 0L)
            .setContentTitle(context.getString(R.string.calls_permission_title))
            .setContentText(context.getString(R.string.calls_permission_body))
            .setContentIntent(open)
            .setAutoCancel(true)
        post(context, TAG_PERMISSION, 1, builder.build())
    }

    fun cancel(context: Context, tag: String, subject: String) {
        context.getSystemService(NotificationManager::class.java)?.cancel(tag, idFor(subject))
    }

    private fun base(context: Context, timeoutMs: Long): Notification.Builder {
        ensure(context)
        val public = Notification.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(context.getString(R.string.calls_locked_title))
            .build()
        val builder = Notification.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setVisibility(Notification.VISIBILITY_PRIVATE)
            .setPublicVersion(public)
        if (timeoutMs > 0L) builder.setTimeoutAfter(timeoutMs)
        return builder
    }

    @android.annotation.SuppressLint("MissingPermission") // POST_NOTIFICATIONS is checked first
    private fun post(context: Context, tag: String, id: Int, notification: Notification) {
        if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) return
        context.getSystemService(NotificationManager::class.java)?.notify(tag, id, notification)
    }
}
