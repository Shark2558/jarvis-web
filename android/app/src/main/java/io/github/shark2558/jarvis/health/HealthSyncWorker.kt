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
import io.github.shark2558.jarvis.link.AppState
import io.github.shark2558.jarvis.link.Hello
import java.io.IOException
import java.util.concurrent.TimeoutException

class HealthSyncWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        if (!AppState(applicationContext).canSend()) return Result.success() // linked, and not refused
        try {
            Hello.send(applicationContext)
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
            return Result.retry()
        } catch (e: Exception) {
            Log.i(TAG, "hello not sent: ${e.javaClass.simpleName}")
        }
        return try {
            when (HealthSync.run(applicationContext).outcome) {
                HealthSync.Outcome.FAILED -> Result.retry()
                else -> Result.success() // a plain "no" from the door is not retried
            }
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
            Result.retry()
        } catch (e: TimeoutException) {
            Result.retry()
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
