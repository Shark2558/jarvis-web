// android/app/src/main/java/io/github/shark2558/jarvis/shell/LaunchGate.kt
// R7 D1, D4: what both launchers share. The console opens only once the phone is linked (so the
// first check Chrome ever makes of the site-and-app link finds this phone); until then the set-up
// screen opens instead. And there is no WebView fallback (Google refuses its sign-in in one):
// without a browser that can draw JARVIS full screen, one plain screen says so.
package io.github.shark2558.jarvis.shell

import android.app.Activity
import android.content.Intent
import com.google.androidbrowserhelper.trusted.TwaLauncher
import io.github.shark2558.jarvis.link.AppState
import io.github.shark2558.jarvis.link.SetupActivity

object LaunchGate {
    fun linkedOrSetUp(activity: Activity): Boolean {
        if (AppState(activity).isLinked()) {
            Background.schedule(activity)
            return true
        }
        activity.startActivity(Intent(activity, SetupActivity::class.java))
        activity.finish()
        return false
    }

    val NO_BROWSER: TwaLauncher.FallbackStrategy =
        TwaLauncher.FallbackStrategy { context, _, _, completion ->
            val intent = Intent(context, NoBrowserActivity::class.java)
            context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            completion?.run()
        }
}
