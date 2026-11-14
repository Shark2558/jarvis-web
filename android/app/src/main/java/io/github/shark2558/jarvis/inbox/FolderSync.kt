// android/app/src/main/java/io/github/shark2558/jarvis/inbox/FolderSync.kt
// R7 D16: the DigiLocker folder. Android grants the ONE folder the owner picked (kept across
// restarts) and nothing else; "all files access" is never asked for. Each run lists that folder
// and sends at most three new PDF, JPEG or PNG files of at most 10 MB, each once by its SHA-256,
// through the door's inbox, where each becomes an item for the owner to confirm. A file's type
// is read from its own first bytes. It never changes or deletes a file. Blocking.
package io.github.shark2558.jarvis.inbox

import android.content.ContentResolver
import android.content.Context
import android.net.Uri
import android.provider.DocumentsContract
import io.github.shark2558.jarvis.core.Door
import io.github.shark2558.jarvis.core.Inbox
import io.github.shark2558.jarvis.core.InboxFate
import io.github.shark2558.jarvis.core.InboxRules
import io.github.shark2558.jarvis.core.Payloads
import io.github.shark2558.jarvis.link.AppState
import io.github.shark2558.jarvis.link.DoorClient
import java.io.ByteArrayOutputStream
import java.io.InputStream

object FolderSync {
    private val COLUMNS = arrayOf(
        DocumentsContract.Document.COLUMN_DOCUMENT_ID,
        DocumentsContract.Document.COLUMN_DISPLAY_NAME,
        DocumentsContract.Document.COLUMN_MIME_TYPE,
        DocumentsContract.Document.COLUMN_SIZE,
        DocumentsContract.Document.COLUMN_LAST_MODIFIED,
    )

    /** `sent` files went; `waitStatus` is the door's status when a file had to wait (null: none). */
    data class Run(val sent: Int, val waitStatus: Int? = null)

    fun run(context: Context, tree: Uri): Run {
        val state = AppState(context)
        var waiting: Int? = null
        var note: String? = null
        val resolver = context.contentResolver
        var seen = state.seen()
        var keys = state.seenKeys()
        var sent = 0
        for (file in InboxRules.order(list(resolver, tree))) {
            if (sent >= InboxRules.PER_RUN) break
            val key = Door.sha256Hex("${file.id}|${file.size}|${file.modifiedMs}".toByteArray(Charsets.UTF_8))
            if (key in keys) continue
            val bytes = read(resolver, DocumentsContract.buildDocumentUriUsingTree(tree, file.id)) ?: continue
            val sha = Door.sha256Hex(bytes)
            val mime = InboxRules.sniff(bytes)
            if (sha in seen || mime == null) {
                keys = keys.adding(key)
                continue
            }
            val body = Payloads.inbox(InboxRules.cleanName(file.name), mime, bytes)
            val answer = DoorClient(context).signed("inbox", body, DoorClient.OCTETS)
            // success, or a refusal for good, marks the file; anything else leaves it for the next run
            when (Inbox.fate(answer.status)) {
                InboxFate.SENT -> {
                    keys = keys.adding(key)
                    seen = seen.adding(sha)
                    sent += 1
                }
                InboxFate.REFUSED_FOR_GOOD -> {
                    keys = keys.adding(key)
                    note = "${InboxRules.cleanName(file.name)}: ${answer.refusal?.sentence.orEmpty()}"
                }
                InboxFate.LATER -> {
                    waiting = answer.status
                    note = answer.refusal?.sentence
                    break
                }
            }
        }
        state.saveSeen(seen)
        state.saveSeenKeys(keys)
        if (note != null || sent > 0) state.setInboxNote(note)
        return Run(sent, waiting)
    }

    private fun list(resolver: ContentResolver, tree: Uri): List<InboxRules.Candidate> {
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree))
        val out = ArrayList<InboxRules.Candidate>()
        resolver.query(children, COLUMNS, null, null, null)?.use { cursor ->
            while (cursor.moveToNext()) {
                val id = cursor.getString(0) ?: continue
                out.add(
                    InboxRules.Candidate(
                        id = id,
                        name = cursor.getString(1).orEmpty(),
                        mime = cursor.getString(2).orEmpty(),
                        size = if (cursor.isNull(3)) 0L else cursor.getLong(3),
                        modifiedMs = if (cursor.isNull(4)) 0L else cursor.getLong(4),
                    ),
                )
            }
        }
        return out
    }

    private fun read(resolver: ContentResolver, uri: Uri): ByteArray? =
        resolver.openInputStream(uri)?.use { readCapped(it) }

    private fun readCapped(input: InputStream): ByteArray? {
        val out = ByteArrayOutputStream()
        val buffer = ByteArray(64 * 1024)
        var total = 0L
        var n = input.read(buffer)
        while (n >= 0) {
            total += n
            if (total > InboxRules.MAX_BYTES) return null
            out.write(buffer, 0, n)
            n = input.read(buffer)
        }
        return out.toByteArray()
    }
}
