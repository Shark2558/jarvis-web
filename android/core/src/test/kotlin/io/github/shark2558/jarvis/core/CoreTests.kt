// android/core/src/test/kotlin/io/github/shark2558/jarvis/core/CoreTests.kt
// R7 D24: the JVM tests of `core`, run by `./gradlew :core:jvmTests`. A small runner of its own,
// so `core` needs no test library at all (D24: the Kotlin standard library and nothing else; the
// repository takes only Apache-2.0 or MIT libraries). Every case prints PASS or FAIL; one FAIL,
// or no case at all, makes the task fail.
package io.github.shark2558.jarvis.core

import kotlin.system.exitProcess

class Case(val name: String, val body: () -> Unit)

fun cases(group: String, vararg items: Pair<String, () -> Unit>): List<Case> =
    items.map { (name, body) -> Case("$group: $name", body) }

class CheckFailed(message: String) : AssertionError(message)

fun <T> same(expected: T, actual: T, what: String) {
    if (expected != actual) throw CheckFailed("$what: expected <$expected> but was <$actual>")
}

fun yes(condition: Boolean, what: String) {
    if (!condition) throw CheckFailed(what)
}

fun sameBytes(expected: ByteArray, actual: ByteArray, what: String) {
    if (!expected.contentEquals(actual)) {
        val e = String(expected, Charsets.UTF_8)
        val a = String(actual, Charsets.UTF_8)
        throw CheckFailed("$what: bytes differ\n  expected <$e>\n  actual   <$a>")
    }
}

inline fun <reified E : Throwable> refuses(what: String, block: () -> Unit) {
    var thrown: Throwable? = null
    try {
        block()
    } catch (e: Throwable) {
        thrown = e
    }
    if (thrown == null) throw CheckFailed("$what: nothing was refused")
    if (thrown !is E) {
        throw CheckFailed("$what: threw ${thrown::class.simpleName}, wanted ${E::class.simpleName}")
    }
}

fun allCases(): List<Case> =
    vectorCases() + jsonCases() + doorCases() + sosCases() + dayCases() + launchCases() +
        channelCases() + inboxCases() + smsCases() + replyCases()

fun main() {
    val all = allCases()
    var failed = 0
    for (case in all) {
        try {
            case.body()
            println("PASS ${case.name}")
        } catch (e: Throwable) {
            failed += 1
            println("FAIL ${case.name}: ${e::class.simpleName}: ${e.message}")
        }
    }
    println("core JVM tests: ${all.size - failed} passed, $failed failed, ${all.size} in all")
    if (failed > 0 || all.isEmpty()) exitProcess(1)
}
