// android/core/src/main/kotlin/io/github/shark2558/jarvis/core/JsonRead.kt
// R18 D: the one JSON reader `core` has (R7's core only wrote JSON). It reads what the door's
// answers and the cloud's signed call commands carry into the same `Json` values the writer
// writes, and nothing looser: one value, integers only (a fraction or an exponent is refused, as
// the door's bodies never carry one), no key twice, at most 16 levels deep, no raw control
// character inside a string. Anything else is a `JsonRead.Bad`.
package io.github.shark2558.jarvis.core

object JsonRead {
    class Bad(message: String) : IllegalArgumentException(message)

    private const val MAX_DEPTH = 16
    private const val HEX_DIGITS = 4
    private const val RADIX = 16

    fun parse(text: String): Json {
        val reader = Reader(text)
        val value = reader.value(0)
        reader.space()
        if (!reader.done()) throw Bad("text after the JSON value")
        return value
    }

    /** `parse`, or null for anything that is not JSON of the shapes above. */
    fun parseOrNull(text: String): Json? =
        try {
            parse(text)
        } catch (e: IllegalArgumentException) {
            null
        }

    private class Reader(private val s: String) {
        private var at = 0

        fun done(): Boolean = at >= s.length

        fun space() {
            while (at < s.length && (s[at] == ' ' || s[at] == '\n' || s[at] == '\r' || s[at] == '\t')) at += 1
        }

        fun value(depth: Int): Json {
            if (depth > MAX_DEPTH) throw Bad("nested too deep")
            space()
            if (done()) throw Bad("a value is missing")
            return when (s[at]) {
                '{' -> fields(depth)
                '[' -> items(depth)
                '"' -> Json.Text(text())
                't' -> word("true", Json.Bool(true))
                'f' -> word("false", Json.Bool(false))
                'n' -> word("null", Json.Null)
                else -> number()
            }
        }

        private fun word(w: String, v: Json): Json {
            if (!s.startsWith(w, at)) throw Bad("not a JSON word")
            at += w.length
            return v
        }

        private fun expect(c: Char) {
            space()
            if (done() || s[at] != c) throw Bad("expected '$c'")
            at += 1
        }

        private fun fields(depth: Int): Json.Fields {
            expect('{')
            val out = ArrayList<Pair<String, Json>>()
            space()
            if (!done() && s[at] == '}') {
                at += 1
                return Json.Fields(out)
            }
            while (true) {
                space()
                if (done() || s[at] != '"') throw Bad("a key must be a string")
                val key = text()
                expect(':')
                out.add(key to value(depth + 1))
                space()
                if (done()) throw Bad("an object is not closed")
                if (s[at] == ',') {
                    at += 1
                    continue
                }
                expect('}')
                break
            }
            if (out.map { it.first }.toSet().size != out.size) throw Bad("a key appears twice")
            return Json.Fields(out)
        }

        private fun items(depth: Int): Json.Items {
            expect('[')
            val out = ArrayList<Json>()
            space()
            if (!done() && s[at] == ']') {
                at += 1
                return Json.Items(out)
            }
            while (true) {
                out.add(value(depth + 1))
                space()
                if (done()) throw Bad("a list is not closed")
                if (s[at] == ',') {
                    at += 1
                    continue
                }
                expect(']')
                return Json.Items(out)
            }
        }

        private fun text(): String {
            at += 1 // the opening quote
            val out = StringBuilder()
            while (true) {
                if (done()) throw Bad("a string is not closed")
                val c = s[at]
                at += 1
                when {
                    c == '"' -> return out.toString()
                    c == '\\' -> out.append(escape())
                    c.code < 0x20 -> throw Bad("a control character inside a string")
                    else -> out.append(c)
                }
            }
        }

        private fun escape(): Char {
            if (done()) throw Bad("an escape is cut off")
            val c = s[at]
            at += 1
            return when (c) {
                '"' -> '"'
                '\\' -> '\\'
                '/' -> '/'
                'b' -> '\b'
                'f' -> '\u000C'
                'n' -> '\n'
                'r' -> '\r'
                't' -> '\t'
                'u' -> {
                    if (at + HEX_DIGITS > s.length) throw Bad("a \\u escape is cut off")
                    val hex = s.substring(at, at + HEX_DIGITS)
                    if (!hex.all { it in '0'..'9' || it in 'a'..'f' || it in 'A'..'F' }) throw Bad("not a \\u escape")
                    at += HEX_DIGITS
                    hex.toInt(RADIX).toChar()
                }
                else -> throw Bad("not a JSON escape")
            }
        }

        private fun number(): Json.Num {
            val start = at
            if (s[at] == '-') at += 1
            val digitsStart = at
            while (at < s.length && s[at] in '0'..'9') at += 1
            val digits = s.substring(digitsStart, at)
            if (digits.isEmpty()) throw Bad("not a JSON value")
            if (digits.length > 1 && digits[0] == '0') throw Bad("a number with a leading zero")
            if (at < s.length && (s[at] == '.' || s[at] == 'e' || s[at] == 'E')) throw Bad("integers only")
            val value = s.substring(start, at).toLongOrNull() ?: throw Bad("a number out of range")
            return Json.Num(value)
        }
    }
}

/** A field of an object, or null. */
fun Json.Fields.field(key: String): Json? = fields.firstOrNull { it.first == key }?.second

fun Json.Fields.textOf(key: String): String? = (field(key) as? Json.Text)?.value

fun Json.Fields.longOf(key: String): Long? = (field(key) as? Json.Num)?.value

fun Json.Fields.boolOf(key: String): Boolean? = (field(key) as? Json.Bool)?.value

fun Json.Fields.keys(): List<String> = fields.map { it.first }
