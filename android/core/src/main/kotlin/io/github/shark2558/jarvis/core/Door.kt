// android/core/src/main/kotlin/io/github/shark2558/jarvis/core/Door.kt
// R7 D6: the phone's signed request, as src/jarvis/mobile/contract.py writes it.
//   X-Jarvis-Phone: v1;d=<device id>;t=<unix seconds>;n=<32 hex>;s=<base64url DER signature>
// signed (ECDSA P-256, SHA-256: Android Keystore's "SHA256withECDSA") over
//   "jarvis-phone-v1\n" + device id + "\n" + t + "\n" + n + "\n" + METHOD + "\n" + path + "\n"
//   + hex(sha256(body))
// The path is one of the four door routes and never carries a query string.
package io.github.shark2558.jarvis.core

import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64

object Door {
    const val SCHEME = "jarvis-phone-v1"
    const val HEADER = "X-Jarvis-Phone"
    const val PACKAGE = "io.github.shark2558.jarvis"
    const val LINK_PATH = "/phone/link"
    private const val HEX = "0123456789abcdef"
    private const val MAX_T = 1_000_000_000_000L
    private const val NONCE_BYTES = 16
    private const val POINT_BYTES = 65

    val ROUTES: List<String> = listOf("hello", "health", "inbox", "sos")
    private val PATH = Regex("/phone/v1/(?:hello|health|inbox|sos)")
    private val DEVICE_ID = Regex("ph_[0-9a-f]{12}")
    private val NONCE = Regex("[0-9a-f]{32}")
    private val METHODS = setOf("GET", "POST")

    // An X.509 SubjectPublicKeyInfo of a P-256 key is this fixed prefix and the 65-byte point.
    private val P256_SPKI_PREFIX: ByteArray = unhex("3059301306072a8648ce3d020106082a8648ce3d030107034200")

    fun path(route: String): String {
        require(route in ROUTES) { "not a door route" }
        return "/phone/v1/$route"
    }

    fun isDoorPath(path: String): Boolean = PATH.matches(path)

    fun isDeviceId(id: String): Boolean = DEVICE_ID.matches(id)

    fun signingString(
        deviceId: String,
        t: Long,
        nonce: String,
        method: String,
        path: String,
        body: ByteArray,
    ): ByteArray {
        require(method in METHODS && PATH.matches(path)) { "not a door method or path" }
        val text = listOf(SCHEME, deviceId, t.toString(), nonce, method, path, sha256Hex(body)).joinToString("\n")
        require(text.all { it.code < 0x80 }) { "the signing string is ASCII only" }
        return text.toByteArray(Charsets.US_ASCII)
    }

    fun header(deviceId: String, t: Long, nonce: String, signature: ByteArray): String {
        require(DEVICE_ID.matches(deviceId) && NONCE.matches(nonce)) { "not a device id or nonce" }
        require(t in 0 until MAX_T && signature.isNotEmpty()) { "not a time or signature" }
        return "v1;d=$deviceId;t=$t;n=$nonce;s=${b64url(signature)}"
    }

    fun newNonce(random: SecureRandom = SecureRandom()): String {
        val bytes = ByteArray(NONCE_BYTES)
        random.nextBytes(bytes)
        return hex(bytes)
    }

    fun x962FromSpki(spki: ByteArray): ByteArray {
        val prefix = P256_SPKI_PREFIX
        require(spki.size == prefix.size + POINT_BYTES) { "not a P-256 public key" }
        require(spki.copyOfRange(0, prefix.size).contentEquals(prefix)) { "not a P-256 public key" }
        val point = spki.copyOfRange(prefix.size, spki.size)
        require(point[0] == 0x04.toByte()) { "not an uncompressed point" }
        return point
    }

    fun sha256Hex(data: ByteArray): String = hex(MessageDigest.getInstance("SHA-256").digest(data))

    fun b64url(data: ByteArray): String = Base64.getUrlEncoder().withoutPadding().encodeToString(data)

    fun unb64url(text: String): ByteArray = Base64.getUrlDecoder().decode(text)

    fun hex(data: ByteArray): String {
        val out = StringBuilder(data.size * 2)
        for (b in data) {
            val v = b.toInt() and 0xFF
            out.append(HEX[v shr 4])
            out.append(HEX[v and 0xF])
        }
        return out.toString()
    }

    fun unhex(text: String): ByteArray {
        require(text.length % 2 == 0 && text.all { it in HEX }) { "not lowercase hex" }
        return ByteArray(text.length / 2) { i -> text.substring(2 * i, 2 * i + 2).toInt(16).toByte() }
    }
}
