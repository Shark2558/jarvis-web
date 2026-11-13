// android/app/src/main/java/io/github/shark2558/jarvis/link/PhoneKey.kt
// R7 D5, D6: the phone's key. A P-256 key pair made inside Android Keystore (the phone's secure
// hardware: "the key material remaining non-exportable"); only its public half ever leaves the
// phone, at linking. It signs the door's requests (SHA256withECDSA, DER) and opens nothing else.
package io.github.shark2558.jarvis.link

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.Signature
import java.security.spec.ECGenParameterSpec

object PhoneKey {
    private const val ALIAS = "jarvis_phone_key"
    private const val STORE = "AndroidKeyStore"

    /** The public key as an X.509 SubjectPublicKeyInfo (core turns it into the X9.62 point). */
    fun publicKeySpki(): ByteArray {
        ensure()
        val certificate = keyStore().getCertificate(ALIAS) ?: throw IllegalStateException("the phone key is missing")
        return certificate.publicKey.encoded
    }

    fun sign(data: ByteArray): ByteArray {
        val entry = keyStore().getEntry(ALIAS, null) as? KeyStore.PrivateKeyEntry
            ?: throw IllegalStateException("the phone key is missing")
        val signer = Signature.getInstance("SHA256withECDSA")
        signer.initSign(entry.privateKey)
        signer.update(data)
        return signer.sign()
    }

    fun forget() {
        val store = keyStore()
        if (store.containsAlias(ALIAS)) store.deleteEntry(ALIAS)
    }

    private fun ensure() {
        if (keyStore().containsAlias(ALIAS)) return
        val generator = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, STORE)
        generator.initialize(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
                .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                .setDigests(KeyProperties.DIGEST_SHA256)
                .build(),
        )
        generator.generateKeyPair()
    }

    private fun keyStore(): KeyStore = KeyStore.getInstance(STORE).apply { load(null) }
}
