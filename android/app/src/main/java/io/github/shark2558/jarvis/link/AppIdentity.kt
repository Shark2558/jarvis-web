// android/app/src/main/java/io/github/shark2558/jarvis/link/AppIdentity.kt
// R7 D4, D5: the SHA-256 of the certificate that signed this app (the laptop's debug key for
// `personal`). It reaches the server by itself at linking, so nobody copies 64 characters, and
// the server lists it in /.well-known/assetlinks.json so Chrome vouches for the app.
package io.github.shark2558.jarvis.link

import android.content.Context
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.os.Build
import io.github.shark2558.jarvis.core.Door

object AppIdentity {
    fun signingFingerprint(context: Context): String {
        val manager = context.packageManager
        val info: PackageInfo = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            manager.getPackageInfo(
                context.packageName,
                PackageManager.PackageInfoFlags.of(PackageManager.GET_SIGNING_CERTIFICATES.toLong()),
            )
        } else {
            @Suppress("DEPRECATION")
            manager.getPackageInfo(context.packageName, PackageManager.GET_SIGNING_CERTIFICATES)
        }
        val first = info.signingInfo?.apkContentsSigners?.firstOrNull()
            ?: throw IllegalStateException("the app's signing certificate cannot be read")
        return Door.sha256Hex(first.toByteArray())
    }
}
