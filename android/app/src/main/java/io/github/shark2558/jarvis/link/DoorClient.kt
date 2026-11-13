// android/app/src/main/java/io/github/shark2558/jarvis/link/DoorClient.kt
// R7 D5, D6: the app's only way to the server. One unsigned request, /phone/link (with the
// one-time code), and signed requests to the door's four routes: HTTPS only, no redirect
// followed, no cookie sent or kept, no query string ever (the signature covers the path only).
// Blocking: call it off the main thread.
package io.github.shark2558.jarvis.link

import android.content.Context
import io.github.shark2558.jarvis.BuildConfig
import io.github.shark2558.jarvis.core.Door
import io.github.shark2558.jarvis.core.Payloads
import io.github.shark2558.jarvis.core.Refusal
import io.github.shark2558.jarvis.core.Replies
import org.json.JSONException
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.URL
import javax.net.ssl.HttpsURLConnection

class DoorRefused(val status: Int) : IOException("JARVIS answered $status")

class NotLinked : IllegalStateException("this phone is not linked")

class DoorClient(private val context: Context, private val host: String = BuildConfig.JARVIS_HOST) {
    /** `skewSeconds`: how far the server's clock (its `Date` header) is ahead of the phone's. */
    data class Answer(val status: Int, val body: String, val skewSeconds: Long? = null) {
        val ok: Boolean get() = status in 200..299

        /** Why the door said no, in the app's plain words; null when it said yes. */
        val refusal: Refusal? get() = Replies.explain(status, skewSeconds)
    }

    /** D5: link with the one-time code; returns the device id the server gave. */
    fun link(code: String): String {
        val point = Door.x962FromSpki(PhoneKey.publicKeySpki())
        val body = Payloads.link(
            code = code,
            publicKeyHex = Door.hex(point),
            fingerprintHex = AppIdentity.signingFingerprint(context),
            model = MODEL,
            appVersion = BuildConfig.VERSION_NAME,
        )
        val answer = post(Door.LINK_PATH, body, null, JSON)
        if (!answer.ok) throw DoorRefused(answer.status)
        val id = try {
            JSONObject(answer.body).optString("device_id", "")
        } catch (e: JSONException) {
            ""
        }
        if (!Door.isDeviceId(id)) throw DoorRefused(answer.status)
        AppState(context).saveDeviceId(id)
        return id
    }

    /** D6: a signed request to one of the door's four routes. */
    fun signed(route: String, body: ByteArray, contentType: String = JSON): Answer {
        val deviceId = AppState(context).deviceId() ?: throw NotLinked()
        val path = Door.path(route)
        val t = System.currentTimeMillis() / MILLIS
        val nonce = Door.newNonce()
        val signature = PhoneKey.sign(Door.signingString(deviceId, t, nonce, "POST", path, body))
        val answer = post(path, body, Door.header(deviceId, t, nonce, signature), contentType)
        noteAnswer(answer)
        return answer
    }

    /** Three "this phone is not known" answers in a row: the app says it needs linking again and
     *  its jobs stop sending. The link itself is kept until the owner links again. */
    private fun noteAnswer(answer: Answer) {
        val state = AppState(context)
        val strikes = Replies.strikes(state.strikes(), answer.refusal)
        state.setStrikes(strikes)
        if (Replies.needsLinking(strikes)) state.setNeedsRelink(true) else if (answer.ok) state.setNeedsRelink(false)
    }

    private fun post(path: String, body: ByteArray, header: String?, contentType: String): Answer {
        val connection = URL("https://$host$path").openConnection() as HttpsURLConnection
        try {
            connection.requestMethod = "POST"
            connection.connectTimeout = CONNECT_MS
            connection.readTimeout = READ_MS
            connection.doOutput = true
            connection.useCaches = false
            connection.instanceFollowRedirects = false
            connection.setRequestProperty("Content-Type", contentType)
            if (header != null) connection.setRequestProperty(Door.HEADER, header)
            connection.setFixedLengthStreamingMode(body.size)
            connection.outputStream.use { it.write(body) }
            val status = connection.responseCode
            val serverMs = connection.getHeaderFieldDate("Date", 0L)
            val skew = Replies.skewSeconds(System.currentTimeMillis(), serverMs)
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.use { readCapped(it) } ?: ""
            return Answer(status, text, skew)
        } finally {
            connection.disconnect()
        }
    }

    companion object {
        const val JSON = "application/json"
        const val OCTETS = "application/octet-stream"
        const val MODEL = "phone"
        private const val MILLIS = 1000L
        private const val CONNECT_MS = 15_000
        private const val READ_MS = 30_000
        private const val MAX_REPLY = 64 * 1024

        private fun readCapped(input: InputStream): String {
            val out = ByteArrayOutputStream()
            val buffer = ByteArray(8192)
            var total = 0
            var n = input.read(buffer)
            while (n >= 0) {
                total += n
                if (total > MAX_REPLY) throw IOException("the reply is too long")
                out.write(buffer, 0, n)
                n = input.read(buffer)
            }
            return String(out.toByteArray(), Charsets.UTF_8)
        }
    }
}
