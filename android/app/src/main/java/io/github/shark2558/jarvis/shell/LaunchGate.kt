// android/app/src/main/java/io/github/shark2558/jarvis/shell/LaunchGate.kt
// R7 D1, D4: what both launchers share. The console opens only once the phone is linked (so the
// first check Chrome ever makes of the site-and-app link finds this phone); until then the set-up
// screen opens instead (R18: then, once, the calls screen). And there is no WebView fallback
// (Google refuses its sign-in in one): without a browser that can draw JARVIS full screen, one
// plain screen says so.
package io.github.shark2558.jarvis.shell

import android.app.Activity
import android.content.Intent
import com.google.androidbrowserhelper.trusted.TwaLauncher
import io.github.shark2558.jarvis.calls.CallsLink
import io.github.shark2558.jarvis.calls.CallsSetupActivity
import io.github.shark2558.jarvis.link.AppState
import io.github.shark2558.jarvis.link.SetupActivity

object LaunchGate {
    fun linkedOrSetUp(activity: Activity): Boolean {
        val state = AppState(activity)
        if (state.isLinked()) {
            Background.schedule(activity)
            // R18 D: once linked, the calls screen explains itself first (once); each open tells
            // the cloud what the phone may do now and fetches any call command waiting for it.
            if (!state.asked(CallsSetupActivity.ASKED)) {
                activity.startActivity(Intent(activity, CallsSetupActivity::class.java))
                activity.finish()
                return false
            }
            if (state.canSend()) CallsLink.pullSoon(activity)
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
