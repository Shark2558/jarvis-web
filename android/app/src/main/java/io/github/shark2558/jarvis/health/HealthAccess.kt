// android/app/src/main/java/io/github/shark2558/jarvis/health/HealthAccess.kt
// R7 D17: is Health Connect on this phone (part of Android from 14; an app from the Play Store on
// 9 to 13), and which of JARVIS's permissions does it hold.
package io.github.shark2558.jarvis.health

import android.content.Context
import androidx.health.connect.client.HealthConnectClient

object HealthAccess {
    const val STORE = "market://details?id=com.google.android.apps.healthdata&url=healthconnect%3A%2F%2Fonboarding"

    fun status(context: Context): Int = HealthConnectClient.getSdkStatus(context)

    fun available(context: Context): Boolean = status(context) == HealthConnectClient.SDK_AVAILABLE

    /** Blocking: never on the main thread. */
    fun granted(context: Context): Set<String> {
        if (!available(context)) return emptySet()
        val client = HealthConnectClient.getOrCreate(context)
        return await { client.permissionController.getGrantedPermissions() }
    }
}
