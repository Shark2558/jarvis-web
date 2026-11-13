// android/app/src/main/java/io/github/shark2558/jarvis/shell/ScreenLauncherActivity.kt
// R7 D8, D9: the second launcher, for the Talk tile and the Talk and Camera shortcuts. Other apps
// cannot start it (android:exported="false"); only it adds a launch word, and only one from
// core's allow-list, named by its own intent action. do=talk readies the mic button and never
// starts the microphone; do=look opens the Camera panel with the camera off (the page's rules).
package io.github.shark2558.jarvis.shell

import android.content.Context
import android.content.Intent
import android.net.Uri
import com.google.androidbrowserhelper.trusted.LauncherActivity
import com.google.androidbrowserhelper.trusted.TwaLauncher
import io.github.shark2558.jarvis.BuildConfig
import io.github.shark2558.jarvis.core.Launch
import java.util.Locale

class ScreenLauncherActivity : LauncherActivity() {
    override fun shouldLaunchImmediately(): Boolean = LaunchGate.linkedOrSetUp(this)

    override fun getLaunchingUrl(): Uri =
        Uri.parse(Launch.screenUrl(BuildConfig.JARVIS_HOST, Launch.wordForAction(intent?.action)))

    override fun getUrlForIntent(intent: Intent?): Uri? = null

    override fun getFallbackStrategy(): TwaLauncher.FallbackStrategy = LaunchGate.NO_BROWSER

    companion object {
        fun launchIntent(context: Context, word: String): Intent =
            Intent(context, ScreenLauncherActivity::class.java)
                .setAction(Launch.ACTION_PREFIX + word.uppercase(Locale.ROOT))
    }
}
