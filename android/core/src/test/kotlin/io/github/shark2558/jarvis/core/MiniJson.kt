// android/core/src/test/kotlin/io/github/shark2558/jarvis/core/MiniJson.kt
// A test-only JSON reader for tests/fixtures/r7/phone_vectors.json (D24: `core` has no JSON
// library; the app reads the server's replies with Android's own org.json). Objects keep their
// key order; whole numbers are Long.
package io.github.shark2558.jarvis.core

object MiniJson {
    fun parse(text: String): Any? {
        val reader = Reader(text)
        val value = reader.value()
        reader.skipSpace()
        check(reader.at == text.length) { "text after the JSON value at ${reader.at}" }
        return value
    }

    private class Reader(private val s: String) {
        var at = 0

        fun skipSpace() {
            while (at < s.length && (s[at] == ' ' || s[at] == '\n' || s[at] == '\r' || s[at] == '\t')) {
                at += 1
            }
        }

        fun value(): Any? {
            skipSpace()
            check(at < s.length) { "the JSON ends too early" }
            val c = s[at]
            return when {
                c == '{' -> obj()
                c == '[' -> list()
                c == '"' -> text()
                c == 't' -> word("true", true)
                c == 'f' -> word("false", false)
                c == 'n' -> word("null", null)
                c == '-' || c.isDigit() -> number()
                else -> throw IllegalStateException("unexpected '$c' at $at")
            }
        }

        private fun word(w: String, v: Any?): Any? {
            check(s.startsWith(w, at)) { "expected $w at $at" }
            at += w.length
            return v
        }

        private fun expect(c: Char) {
            check(at < s.length && s[at] == c) { "expected '$c' at $at" }
            at += 1
        }

        private fun obj(): Map<String, Any?> {
            val out = LinkedHashMap<String, Any?>()
            expect('{')
            skipSpace()
            if (at < s.length && s[at] == '}') {
                at += 1
                return out
            }
            var more = true
            while (more) {
                skipSpace()
                val key = text()
                skipSpace()
                expect(':')
                out[key] = value()
                skipSpace()
                check(at < s.length) { "an object is not closed" }
                val c = s[at]
                at += 1
                if (c == '}') more = false else check(c == ',') { "expected ',' or '}' at $at" }
            }
            return out
        }

        private fun list(): List<Any?> {
            val out = ArrayList<Any?>()
            expect('[')
            skipSpace()
            if (at < s.length && s[at] == ']') {
                at += 1
                return out
            }
            var more = true
            while (more) {
                out.add(value())
                skipSpace()
                check(at < s.length) { "a list is not closed" }
                val c = s[at]
                at += 1
                if (c == ']') more = false else check(c == ',') { "expected ',' or ']' at $at" }
            }
            return out
        }

        private fun text(): String {
            expect('"')
            val out = StringBuilder()
            var closed = false
            while (!closed) {
                check(at < s.length) { "a string is not closed" }
                val c = s[at]
                at += 1
                if (c == '"') {
                    closed = true
                    continue
                }
                if (c != '\\') {
                    out.append(c)
                    continue
                }
                val e = s[at]
                at += 1
                when (e) {
                    '"' -> out.append('"')
                    '\\' -> out.append('\\')
                    '/' -> out.append('/')
                    'b' -> out.append('\b')
                    'f' -> out.append('\u000C')
                    'n' -> out.append('\n')
                    'r' -> out.append('\r')
                    't' -> out.append('\t')
                    'u' -> {
                        out.append(s.substring(at, at + 4).toInt(16).toChar())
                        at += 4
                    }
                    else -> throw IllegalStateException("a bad escape at $at")
                }
            }
            return out.toString()
        }

        private fun number(): Any {
            val start = at
            if (s[at] == '-') at += 1
            while (at < s.length && (s[at].isDigit() || s[at] == '.' || s[at] == 'e' ||
                    s[at] == 'E' || s[at] == '+' || s[at] == '-')
            ) {
                at += 1
            }
            val t = s.substring(start, at)
            return t.toLongOrNull() ?: t.toDouble()
        }
    }
}

@Suppress("UNCHECKED_CAST")
fun Any?.asMap(): Map<String, Any?> = this as Map<String, Any?>

@Suppress("UNCHECKED_CAST")
fun Any?.asList(): List<Any?> = this as List<Any?>

fun Map<String, Any?>.text(key: String): String = this[key] as String

fun Map<String, Any?>.whole(key: String): Long = (this[key] as Number).toLong()

fun Map<String, Any?>.flag(key: String): Boolean = this[key] as Boolean
