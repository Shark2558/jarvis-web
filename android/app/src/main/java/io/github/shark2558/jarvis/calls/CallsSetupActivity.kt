// android/app/src/main/java/io/github/shark2558/jarvis/calls/CallsSetupActivity.kt
// R18 D: the first-run explanation screen for JARVIS's calls, shown once after the app is linked
// (and again from the "Allow JARVIS to place calls" notification). It says what JARVIS will do with
// the phone (place the calls he approves, answer only when he switched answering on, end only its
// own calls, try to move a call's sound) and what it never does (hear a call through the phone,
// read his call log or contacts, call anyone without his tap). Two choices: the three permissions
// calls need, and, apart, the caller's number (READ_CALL_LOG, see CallsAccess) for answering missed
// calls with a contacts rule. "Done" opens JARVIS. Nothing is asked without his tap.
package io.github.shark2558.jarvis.calls

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import io.github.shark2558.jarvis.R
import io.github.shark2558.jarvis.link.AppState
import io.github.shark2558.jarvis.shell.IconLauncherActivity
import io.github.shark2558.jarvis.ui.Look
import io.github.shark2558.jarvis.ui.SystemBars

class CallsSetupActivity : ComponentActivity() {
    private val askCore =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { refresh() }
    private val askNumber =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { refresh() }

    private lateinit var state: TextView
    private lateinit var numberState: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_calls_setup)
        val root = findViewById<View>(R.id.calls_root)
        SystemBars.pad(this, root)
        Look.fonts(this, root)
        state = findViewById(R.id.calls_state)
        numberState = findViewById(R.id.calls_number_state)
        AppState(this).setAsked(ASKED)
        findViewById<Button>(R.id.calls_allow).setOnClickListener { askCore.launch(CallsAccess.CORE) }
        findViewById<Button>(R.id.calls_number).setOnClickListener { askNumber.launch(CallsAccess.NUMBER) }
        findViewById<Button>(R.id.calls_done).setOnClickListener {
            CallsLink.pullSoon(this) // tell JARVIS what the phone may do now
            startActivity(Intent(this, IconLauncherActivity::class.java))
            finish()
        }
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    private fun refresh() {
        state.setText(if (CallsAccess.coreGranted(this)) R.string.calls_setup_allowed else R.string.calls_setup_not_yet)
        numberState.setText(if (CallsAccess.granted(this, CallsAccess.NUMBER)) R.string.calls_setup_allowed else R.string.calls_setup_number_off)
    }

    companion object {
        /** AppState's "asked" word: the screen opens by itself only until he has seen it once. */
        const val ASKED = "calls"
    }
}
