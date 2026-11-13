// android/app/src/main/java/io/github/shark2558/jarvis/shell/Tiles.kt
// R7 D9: a tile opens its screen and closes the shade. From Android 14 that must be
// startActivityAndCollapse(PendingIntent): Android 14 refuses the older Intent form for an app
// that targets it.
package io.github.shark2558.jarvis.shell

import android.annotation.SuppressLint
import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import android.service.quicksettings.TileService

object Tiles {
    const val REQUEST_TALK = 1
    const val REQUEST_SOS = 2

    @SuppressLint("StartActivityAndCollapseDeprecated") // the Intent form only below Android 14
    fun open(service: TileService, intent: Intent, request: Int) {
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            val pending = PendingIntent.getActivity(
                service,
                request,
                intent,
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
            service.startActivityAndCollapse(pending)
        } else {
            @Suppress("DEPRECATION")
            service.startActivityAndCollapse(intent)
        }
    }
}
