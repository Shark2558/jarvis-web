// android/app/src/main/java/io/github/shark2558/jarvis/health/PrivacyActivity.kt
// R7 D17: the page Health Connect opens from its "privacy policy" link (Health Connect requires
// it): four plain lines. Reached from outside only through Health Connect's two entries (the
// rationale action, and on Android 14 and newer the alias behind START_VIEW_PERMISSION_USAGE).
package io.github.shark2558.jarvis.health

import android.app.Activity
import android.os.Bundle
import android.view.View
import android.widget.Button
import io.github.shark2558.jarvis.R
import io.github.shark2558.jarvis.ui.Look
import io.github.shark2558.jarvis.ui.SystemBars

class PrivacyActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_privacy)
        val root = findViewById<View>(R.id.privacy_root)
        SystemBars.pad(this, root)
        Look.fonts(this, root)
        findViewById<Button>(R.id.privacy_close).setOnClickListener { finish() }
    }
}
