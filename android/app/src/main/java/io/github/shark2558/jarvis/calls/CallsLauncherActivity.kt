// android/app/src/main/java/io/github/shark2558/jarvis/calls/CallsLauncherActivity.kt
// R18 D: opens JARVIS full screen at its Calls panel (/?source=app&open=calls), where a card whose
// number was never called is approved with his passkey. Other apps cannot start it
// (android:exported="false"), and it reads nothing from the intent: one fixed address.
package io.github.shark2558.jarvis.calls

import android.content.Intent
import android.net.Uri
import com.google.androidbrowserhelper.trusted.LauncherActivity
import com.google.androidbrowserhelper.trusted.TwaLauncher
import io.github.shark2558.jarvis.BuildConfig
import io.github.shark2558.jarvis.core.CallLaunch
import io.github.shark2558.jarvis.shell.LaunchGate

class CallsLauncherActivity : LauncherActivity() {
    override fun shouldLaunchImmediately(): Boolean = LaunchGate.linkedOrSetUp(this)

    override fun getLaunchingUrl(): Uri = Uri.parse(CallLaunch.panelUrl(BuildConfig.JARVIS_HOST))

    override fun getUrlForIntent(intent: Intent?): Uri? = null

    override fun getFallbackStrategy(): TwaLauncher.FallbackStrategy = LaunchGate.NO_BROWSER
}
