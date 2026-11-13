// android/app/src/main/java/io/github/shark2558/jarvis/shell/NotifyChannels.kt
// R7 D10: three Android channels, so the owner sets each one's sound once in Android: Urgent
// (burglar, hazard, disaster, SOS, a phone linked), Alerts, Nudges.
package io.github.shark2558.jarvis.shell

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import io.github.shark2558.jarvis.R
import io.github.shark2558.jarvis.core.AlertChannel

object NotifyChannels {
    fun ensure(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        val channels = AlertChannel.entries.map { channel ->
            NotificationChannel(channel.id, context.getString(nameOf(channel)), importanceOf(channel)).apply {
                description = context.getString(aboutOf(channel))
            }
        }
        manager.createNotificationChannels(channels)
    }

    private fun nameOf(channel: AlertChannel): Int = when (channel) {
        AlertChannel.URGENT -> R.string.channel_urgent
        AlertChannel.ALERTS -> R.string.channel_alerts
        AlertChannel.NUDGES -> R.string.channel_nudges
    }

    private fun aboutOf(channel: AlertChannel): Int = when (channel) {
        AlertChannel.URGENT -> R.string.channel_urgent_about
        AlertChannel.ALERTS -> R.string.channel_alerts_about
        AlertChannel.NUDGES -> R.string.channel_nudges_about
    }

    private fun importanceOf(channel: AlertChannel): Int = when (channel) {
        AlertChannel.URGENT -> NotificationManager.IMPORTANCE_HIGH
        AlertChannel.ALERTS -> NotificationManager.IMPORTANCE_DEFAULT
        AlertChannel.NUDGES -> NotificationManager.IMPORTANCE_LOW
    }
}
