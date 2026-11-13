// android/app/src/main/java/io/github/shark2558/jarvis/inbox/FolderWorker.kt
// R7 D16: the hourly job (and once when the app opens) for the one folder the owner picked.
package io.github.shark2558.jarvis.inbox

import android.content.Context
import android.util.Log
import androidx.work.Worker
import androidx.work.WorkerParameters
import io.github.shark2558.jarvis.core.Replies
import io.github.shark2558.jarvis.link.AppState
import java.io.IOException

class FolderWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val state = AppState(applicationContext)
        val tree = state.folder() ?: return Result.success()
        if (!state.canSend()) return Result.success() // not linked, or the door refused this phone
        return try {
            val run = FolderSync.run(applicationContext, tree)
            val wait = run.waitStatus
            if (wait != null && Replies.worthRetry(wait)) Result.retry() else Result.success()
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
            Result.retry()
        } catch (e: SecurityException) {
            state.setFolder(null) // Android took the folder back: the set-up screen offers it again
            Result.success()
        } catch (e: IOException) {
            Result.retry()
        } catch (e: Exception) {
            Log.w(TAG, "folder read stopped: ${e.javaClass.simpleName}")
            Result.success()
        }
    }

    private companion object {
        const val TAG = "JarvisFolder"
    }
}
