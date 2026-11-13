// android/app/src/main/java/io/github/shark2558/jarvis/health/HealthSyncWorker.kt
// R7 D17, D19: the 6-hourly job (and once when the app opens). It refreshes "hello" (so the SOS
// numbers for the text message stay current), then reads the watch. Without Health Connect's
// background switch Android refuses a read from here; the set-up screen then reads while it is
// open. Logs carry the kind of a failure, never a value.
package io.github.shark2558.jarvis.health

import android.content.Context
import android.util.Log
import androidx.work.Worker
import androidx.work.WorkerParameters
import io.github.shark2558.jarvis.link.Hello
import java.io.IOException

class HealthSyncWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        try {
            Hello.send(applicationContext)
        } catch (e: Exception) {
            Log.i(TAG, "hello not sent: ${e.javaClass.simpleName}")
        }
        return try {
            when (HealthSync.run(applicationContext)) {
                HealthSync.Outcome.FAILED -> Result.retry()
                else -> Result.success()
            }
        } catch (e: SecurityException) {
            Log.i(TAG, "watch read refused in the background")
            Result.success()
        } catch (e: IOException) {
            Result.retry()
        } catch (e: Exception) {
            Log.w(TAG, "watch read stopped: ${e.javaClass.simpleName}")
            Result.success()
        }
    }

    private companion object {
        const val TAG = "JarvisWatch"
    }
}
