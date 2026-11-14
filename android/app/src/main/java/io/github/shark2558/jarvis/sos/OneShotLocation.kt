// android/app/src/main/java/io/github/shark2558/jarvis/sos/OneShotLocation.kt
// R7 D19: one location fix when the SOS screen opens, 10 seconds at most, through Android's own
// location service (no Google Play services library). The fix is used once, for the SOS body and
// the text message, and is never stored, logged or put in an address.
package io.github.shark2558.jarvis.sos

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationManager
import android.os.Build
import android.os.CancellationSignal
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import androidx.core.location.LocationManagerCompat
import io.github.shark2558.jarvis.core.Fix
import kotlin.math.roundToLong

class OneShotLocation(private val context: Context) {
    private val handler = Handler(Looper.getMainLooper())
    private var signal: CancellationSignal? = null
    private var finished = false

    fun granted(): Boolean =
        context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
            context.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED

    @SuppressLint("MissingPermission") // granted() is checked first
    fun request(timeoutMs: Long, done: (Fix?) -> Unit) {
        val manager = context.getSystemService(LocationManager::class.java)
        if (!granted() || manager == null) {
            done(null)
            return
        }
        val finish: (Location?) -> Unit = { location ->
            if (!finished) {
                finished = true
                signal?.cancel()
                handler.removeCallbacksAndMessages(null)
                done(location?.let { toFix(it) })
            }
        }
        handler.postDelayed({ finish(lastKnown(manager)) }, timeoutMs)
        val provider = providerOf(manager)
        if (provider == null) {
            finish(lastKnown(manager))
            return
        }
        val cancel = CancellationSignal()
        signal = cancel
        LocationManagerCompat.getCurrentLocation(manager, provider, cancel, context.mainExecutor) { location ->
            finish(location ?: lastKnown(manager))
        }
    }

    fun stop() {
        finished = true
        signal?.cancel()
        handler.removeCallbacksAndMessages(null)
    }

    private fun providerOf(manager: LocationManager): String? {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S &&
            manager.hasProvider(LocationManager.FUSED_PROVIDER) &&
            manager.isProviderEnabled(LocationManager.FUSED_PROVIDER)
        ) {
            return LocationManager.FUSED_PROVIDER
        }
        if (manager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)) return LocationManager.NETWORK_PROVIDER
        if (manager.isProviderEnabled(LocationManager.GPS_PROVIDER)) return LocationManager.GPS_PROVIDER
        return null
    }

    @SuppressLint("MissingPermission") // granted() is checked first
    private fun lastKnown(manager: LocationManager): Location? {
        if (!granted()) return null
        val now = SystemClock.elapsedRealtimeNanos()
        val known = ArrayList<Location>()
        for (provider in listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)) {
            try {
                manager.getLastKnownLocation(provider)?.let { known.add(it) }
            } catch (e: IllegalArgumentException) {
                // the provider is not on this phone
            } catch (e: SecurityException) {
                return null
            }
        }
        return known
            .filter { now - it.elapsedRealtimeNanos <= MAX_AGE_NS }
            .minByOrNull { if (it.hasAccuracy()) it.accuracy else Float.MAX_VALUE }
    }

    private fun toFix(location: Location): Fix {
        val ageNs = SystemClock.elapsedRealtimeNanos() - location.elapsedRealtimeNanos
        return Fix(
            latE6 = (location.latitude * MICRO).roundToLong(),
            lonE6 = (location.longitude * MICRO).roundToLong(),
            accuracyM = if (location.hasAccuracy()) maxOf(1L, location.accuracy.roundToLong()) else 0L,
            ageS = maxOf(0L, ageNs / NANOS_PER_S),
            atEpochS = location.time / MILLIS_PER_S,
        )
    }

    private companion object {
        const val MICRO = 1_000_000.0
        const val NANOS_PER_S = 1_000_000_000L
        const val MILLIS_PER_S = 1000L
        const val MAX_AGE_NS = 120L * 1_000_000_000L
    }
}
