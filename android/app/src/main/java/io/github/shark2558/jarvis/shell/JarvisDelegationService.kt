// android/app/src/main/java/io/github/shark2558/jarvis/shell/JarvisDelegationService.kt
// R7 D10: the server keeps sending Web Push as today; with the app installed and vouched for,
// Chrome hands each notification to this service, so alerts carry JARVIS's icon and obey its
// channels. The push worker sets each notification's tag to the alert's kind
// (phone-contract.md section 6); core's Channels reads it, and a tag it cannot read goes to
// Alerts. The library's token store checks that the caller is the browser this app linked with.
package io.github.shark2558.jarvis.shell

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationManager
import androidx.core.app.NotificationManagerCompat
import com.google.androidbrowserhelper.trusted.DelegationService
import io.github.shark2558.jarvis.core.Channels

class JarvisDelegationService : DelegationService() {
    override fun onCreate() {
        super.onCreate()
        NotifyChannels.ensure(this)
    }

    @SuppressLint("MissingPermission") // POST_NOTIFICATIONS is checked on the first line
    override fun onNotifyNotificationWithChannel(
        platformTag: String,
        platformId: Int,
        notification: Notification,
        channelName: String,
    ): Boolean {
        if (!NotificationManagerCompat.from(this).areNotificationsEnabled()) return false
        NotifyChannels.ensure(this)
        val channel = Channels.forTag(platformTag)
        val sorted = Notification.Builder.recoverBuilder(this, notification).setChannelId(channel.id).build()
        val manager = getSystemService(NotificationManager::class.java) ?: return false
        manager.notify(platformTag, platformId, sorted)
        return true
    }

    override fun onAreNotificationsEnabled(channelName: String): Boolean =
        NotificationManagerCompat.from(this).areNotificationsEnabled()
}
