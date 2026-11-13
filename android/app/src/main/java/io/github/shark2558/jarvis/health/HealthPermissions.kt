// android/app/src/main/java/io/github/shark2558/jarvis/health/HealthPermissions.kt
// R7 D17: the app reads three kinds from Health Connect, and the background read. Not resting
// heart rate (a separate record type behind its own permission): "lowest" says enough.
package io.github.shark2558.jarvis.health

import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord

object HealthPermissions {
    val STEPS: String = HealthPermission.getReadPermission(StepsRecord::class)
    val HEART: String = HealthPermission.getReadPermission(HeartRateRecord::class)
    val SLEEP: String = HealthPermission.getReadPermission(SleepSessionRecord::class)
    val READ: Set<String> = setOf(STEPS, HEART, SLEEP)
    const val BACKGROUND = "android.permission.health.READ_HEALTH_DATA_IN_BACKGROUND"
    val ALL: Set<String> = READ + BACKGROUND
}
