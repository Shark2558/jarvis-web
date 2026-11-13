// android/app/src/main/java/io/github/shark2558/jarvis/sos/ContactsVault.kt
// R7 D19: so that the SMS screen works with no internet, the phone keeps the owner's label and
// the SOS contacts' numbers itself, sealed with AES-GCM under a key held in the phone's secure
// hardware (Android Keystore). Never backed up, never logged.
package io.github.shark2558.jarvis.sos

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import io.github.shark2558.jarvis.core.Door
import io.github.shark2558.jarvis.link.Hello
import io.github.shark2558.jarvis.link.SosBook
import org.json.JSONArray
import org.json.JSONObject
import java.security.GeneralSecurityException
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

object ContactsVault {
    private const val ALIAS = "jarvis_sos_numbers"
    private const val STORE = "AndroidKeyStore"
    private const val PREFS = "jarvis_sos"
    private const val BOOK = "book"
    private const val CIPHER = "AES/GCM/NoPadding"
    private const val TAG_BITS = 128
    private const val KEY_BITS = 256

    fun save(context: Context, book: SosBook) {
        val cipher = Cipher.getInstance(CIPHER)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val sealed = cipher.doFinal(encode(book).toByteArray(Charsets.UTF_8))
        val text = Door.b64url(cipher.iv) + "." + Door.b64url(sealed)
        prefs(context).edit().putString(BOOK, text).apply()
    }

    /** No numbers on the phone: the server's answer had none, or the link was forgotten. */
    fun clear(context: Context) {
        prefs(context).edit().remove(BOOK).apply()
    }

    fun load(context: Context): SosBook? {
        val text = prefs(context).getString(BOOK, null) ?: return null
        val parts = text.split('.')
        if (parts.size != 2) return null
        return try {
            val cipher = Cipher.getInstance(CIPHER)
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(TAG_BITS, Door.unb64url(parts[0])))
            val plain = String(cipher.doFinal(Door.unb64url(parts[1])), Charsets.UTF_8)
            Hello.parseBook("{\"sos\":$plain}")
        } catch (e: GeneralSecurityException) {
            null
        } catch (e: IllegalArgumentException) {
            null
        }
    }

    private fun prefs(context: Context) =
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    private fun encode(book: SosBook): String {
        val list = JSONArray()
        for (c in book.contacts) list.put(JSONObject().put("label", c.label).put("phone", c.phone))
        return JSONObject().put("label", book.label).put("contacts", list).toString()
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance(STORE).apply { load(null) }
        val existing = store.getKey(ALIAS, null)
        if (existing is SecretKey) return existing
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, STORE)
        generator.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(KEY_BITS)
                .build(),
        )
        return generator.generateKey()
    }
}
