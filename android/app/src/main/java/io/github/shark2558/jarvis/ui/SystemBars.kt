// android/app/src/main/java/io/github/shark2558/jarvis/ui/SystemBars.kt
// R7 D19: the native screens draw edge to edge (Android 15 and newer enforce it for an app that
// targets 36), so each one pads its root view inside the system bars, the camera cut-out and the
// keyboard. Nothing, the SOS screen's Cancel above all, can sit under a bar.
package io.github.shark2558.jarvis.ui

import android.app.Activity
import android.view.View
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat

object SystemBars {
    fun pad(activity: Activity, root: View) {
        WindowCompat.enableEdgeToEdge(activity.window)
        val left = root.paddingLeft
        val top = root.paddingTop
        val right = root.paddingRight
        val bottom = root.paddingBottom
        ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
            val bars = insets.getInsets(
                WindowInsetsCompat.Type.systemBars() or
                    WindowInsetsCompat.Type.displayCutout() or
                    WindowInsetsCompat.Type.ime(),
            )
            view.setPadding(left + bars.left, top + bars.top, right + bars.right, bottom + bars.bottom)
            WindowInsetsCompat.CONSUMED
        }
        ViewCompat.requestApplyInsets(root)
    }
}
