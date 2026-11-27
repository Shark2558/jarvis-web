// android/app/src/main/java/io/github/shark2558/jarvis/calls/CallsLink.kt
// R18 D: the phone's one exchange with the cloud about calls, on R7's signed door
// (`POST /phone/v1/calls`): it sends the events not yet taken, the commands it acted on and what it
// may do now, and the answer carries the cloud's key, the answering rule and the pending signed
// commands. Every command is checked by core's CallCommands before anything is done with it.
// Blocking: call it off the main thread. A refused or failed exchange keeps the events for the next.
package io.github.shark2558.jarvis.calls

import android.content.Context
import android.util.Log
import io.github.shark2558.jarvis.BuildConfig
import io.github.shark2558.jarvis.core.CallEvent
import io.github.shark2558.jarvis.core.CallPayloads
import io.github.shark2558.jarvis.core.CallWire
import io.github.shark2558.jarvis.core.CallsAnswer
import io.github.shark2558.jarvis.link.AppState
import io.github.shark2558.jarvis.link.DoorClient
import java.io.IOException
import java.security.GeneralSecurityException
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

object CallsLink {
    private const val TAG = "JarvisCalls"
    private const val MILLIS = 1000L
    private const val WORKERS = 3

    @Volatile
    private var skewSeconds: Long = 0L

    /** A few threads for the exchanges: a ringing call's wait for its ring must not hold up the
     *  report that he picked it up. The store's LOCK keeps a command from being acted on twice. */
    val worker: ExecutorService = Executors.newFixedThreadPool(WORKERS)

    /** The cloud's clock as well as the phone can tell (the door's Date header). */
    fun nowS(): Long = System.currentTimeMillis() / MILLIS + skewSeconds

    fun exchange(context: Context, fresh: List<CallEvent>, wait: Int): CallsAnswer? {
        val app = context.applicationContext
        if (!AppState(app).canSend()) return null
        val store = CallsStore(app)
        val (events, acks) = synchronized(CallsStore.LOCK) {
            store.queue(fresh)
            store.queued().take(CallWire.MAX_EVENTS) to store.acks()
        }
        val body = CallPayloads.body(BuildConfig.VERSION_NAME, CallsAccess.can(app), events, acks, wait.coerceIn(0, CallWire.MAX_WAIT_S))
        val reply = try {
            DoorClient(app).signed(CallWire.ROUTE, body)
        } catch (e: IOException) {
            Log.i(TAG, "calls exchange failed: ${e.javaClass.simpleName}")
            return null
        } catch (e: GeneralSecurityException) {
            Log.w(TAG, "calls exchange not signed: ${e.javaClass.simpleName}")
            return null
        } catch (e: IllegalStateException) {
            Log.w(TAG, "calls exchange not possible: ${e.javaClass.simpleName}")
            return null
        }
        reply.skewSeconds?.let { skewSeconds = it }
        if (!reply.ok) {
            Log.i(TAG, "calls exchange refused: ${reply.status}")
            return null
        }
        val answer = CallPayloads.answer(reply.body) ?: return null
        synchronized(CallsStore.LOCK) {
            store.drop(events.map { it.id }.toSet())
            store.clearAcks(acks)
            store.saveAnswer(answer)
        }
        return answer
    }

    /** Ask, act on every good command, then say what was done (that also acknowledges them). */
    fun pullAndAct(context: Context, fresh: List<CallEvent> = emptyList(), wait: Int = 0): CallsAnswer? {
        val app = context.applicationContext
        val answer = exchange(app, fresh, wait) ?: return null
        val results = CallActions.actOn(app, answer)
        val pendingAcks = synchronized(CallsStore.LOCK) { CallsStore(app).acks() }
        if (results.isNotEmpty() || pendingAcks.isNotEmpty()) exchange(app, results, 0)
        return answer
    }

    /** The same, on the worker thread (from the notification service, a launch or a tap). */
    fun pullSoon(context: Context, fresh: List<CallEvent> = emptyList()) {
        val app = context.applicationContext
        worker.execute { pullAndAct(app, fresh) }
    }
}
