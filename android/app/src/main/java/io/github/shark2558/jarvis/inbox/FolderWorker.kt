// android/app/src/main/java/io/github/shark2558/jarvis/inbox/FolderWorker.kt
// R7 D16: the hourly job (and once when the app opens) for the one folder the owner picked.
package io.github.shark2558.jarvis.inbox

import android.content.Context
import android.util.Log
import androidx.work.Worker
import androidx.work.WorkerParameters
import io.github.shark2558.jarvis.link.AppState
import java.io.IOException

class FolderWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val state = AppState(applicationContext)
        val tree = state.folder() ?: return Result.success()
        if (!state.isLinked()) return Result.success()
        return try {
            FolderSync.run(applicationContext, tree)
            Result.success()
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
