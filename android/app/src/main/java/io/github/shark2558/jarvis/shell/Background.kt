// android/app/src/main/java/io/github/shark2558/jarvis/shell/Background.kt
// R7 D16, D17, D22: the only background work. The watch read every 6 hours and the folder about
// every hour, each also once when the app opens; only with a network. Ordinary work, never
// expedited: on Android 9 to 11 expedited work runs as a foreground service, and the manifest
// removes that permission because JARVIS starts no such service.
package io.github.shark2558.jarvis.shell

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequest
import androidx.work.PeriodicWorkRequest
import androidx.work.WorkManager
import io.github.shark2558.jarvis.health.HealthSyncWorker
import io.github.shark2558.jarvis.inbox.FolderWorker
import io.github.shark2558.jarvis.link.AppState
import java.util.concurrent.TimeUnit

object Background {
    private const val WATCH = "jarvis_watch_6h"
    private const val WATCH_NOW = "jarvis_watch_now"
    private const val FOLDER = "jarvis_folder_1h"
    private const val FOLDER_NOW = "jarvis_folder_now"

    fun schedule(context: Context) {
        val work = WorkManager.getInstance(context.applicationContext)
        val online = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
        val watch = PeriodicWorkRequest.Builder(HealthSyncWorker::class.java, 6, TimeUnit.HOURS)
            .setConstraints(online)
            .build()
        work.enqueueUniquePeriodicWork(WATCH, ExistingPeriodicWorkPolicy.KEEP, watch)
        val watchNow = OneTimeWorkRequest.Builder(HealthSyncWorker::class.java).setConstraints(online).build()
        work.enqueueUniqueWork(WATCH_NOW, ExistingWorkPolicy.KEEP, watchNow)
        if (AppState(context).folder() == null) {
            work.cancelUniqueWork(FOLDER)
            return
        }
        val folder = PeriodicWorkRequest.Builder(FolderWorker::class.java, 1, TimeUnit.HOURS)
            .setConstraints(online)
            .build()
        work.enqueueUniquePeriodicWork(FOLDER, ExistingPeriodicWorkPolicy.KEEP, folder)
        val folderNow = OneTimeWorkRequest.Builder(FolderWorker::class.java).setConstraints(online).build()
        work.enqueueUniqueWork(FOLDER_NOW, ExistingWorkPolicy.KEEP, folderNow)
    }
}
