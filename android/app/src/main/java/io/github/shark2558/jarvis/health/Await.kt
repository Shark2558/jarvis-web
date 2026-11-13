// android/app/src/main/java/io/github/shark2558/jarvis/health/Await.kt
// R7 D24: Health Connect's client speaks Kotlin `suspend` functions. The app adds no coroutine
// library for them: this runs one call with the standard library's own coroutine start and
// waits for its answer, on a worker thread (never the main thread).
package io.github.shark2558.jarvis.health

import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException
import java.util.concurrent.atomic.AtomicReference
import kotlin.coroutines.Continuation
import kotlin.coroutines.EmptyCoroutineContext
import kotlin.coroutines.startCoroutine

private const val AWAIT_MS = 30_000L

internal fun <T> await(block: suspend () -> T): T {
    val done = CountDownLatch(1)
    val outcome = AtomicReference<Result<T>>()
    block.startCoroutine(
        Continuation<T>(EmptyCoroutineContext) { result ->
            outcome.set(result)
            done.countDown()
        },
    )
    if (!done.await(AWAIT_MS, TimeUnit.MILLISECONDS)) {
        throw TimeoutException("Health Connect did not answer in time")
    }
    return outcome.get().getOrThrow()
}
