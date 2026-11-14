// android/app/src/main/java/io/github/shark2558/jarvis/shell/NoBrowserActivity.kt
// R7 D1: with no browser that can show JARVIS full screen, this one plain screen.
package io.github.shark2558.jarvis.shell

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.TextView
import io.github.shark2558.jarvis.R
import io.github.shark2558.jarvis.ui.Look
import io.github.shark2558.jarvis.ui.SystemBars

class NoBrowserActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_no_browser)
        val root = findViewById<View>(R.id.nobrowser_root)
        SystemBars.pad(this, root)
        Look.fonts(this, root)
        findViewById<Button>(R.id.nobrowser_store).setOnClickListener {
            try {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(CHROME_IN_STORE)))
            } catch (e: ActivityNotFoundException) {
                findViewById<TextView>(R.id.nobrowser_status).setText(R.string.nobrowser_no_store)
            }
        }
    }

    private companion object {
        const val CHROME_IN_STORE = "market://details?id=com.android.chrome"
    }
}
