// android/app/src/main/java/io/github/shark2558/jarvis/shell/IconLauncherActivity.kt
// R7 D1, D8, D15: the icon. It opens JARVIS full screen in the phone's browser (a Trusted Web
// Activity) and ALWAYS at /?source=app: getLaunchingUrl() ignores any address an incoming intent
// carries, and getUrlForIntent() forwards none, so another app cannot slip a launch word (or any
// address) in through this exported screen. A share from another app passes through here to the
// web share target (/app/share/in), where it waits on the phone until the owner chooses.
package io.github.shark2558.jarvis.shell

import android.content.Intent
import android.net.Uri
import com.google.androidbrowserhelper.trusted.LauncherActivity
import com.google.androidbrowserhelper.trusted.TwaLauncher
import io.github.shark2558.jarvis.BuildConfig
import io.github.shark2558.jarvis.core.Launch

class IconLauncherActivity : LauncherActivity() {
    override fun shouldLaunchImmediately(): Boolean = LaunchGate.linkedOrSetUp(this)

    override fun getLaunchingUrl(): Uri = Uri.parse(Launch.iconUrl(BuildConfig.JARVIS_HOST))

    override fun getUrlForIntent(intent: Intent?): Uri? = null

    override fun getFallbackStrategy(): TwaLauncher.FallbackStrategy = LaunchGate.NO_BROWSER
}
