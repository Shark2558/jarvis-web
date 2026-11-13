// android/core/build.gradle.kts -- R7 D24: `core` is plain Kotlin with no Android import and no
// library but the Kotlin standard library (and the JDK's own java.* classes, which Android has
// too). Its JVM tests are a small runner of their own (no test framework: nothing outside the
// standard library, and nothing but Apache-2.0 or MIT code), run by `./gradlew :core:jvmTests`
// against the server's shared vectors, tests/fixtures/r7/phone_vectors.json.
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.kotlin.jvm)
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

// The JVM tests read the same file as the server's tests (D24); it sits beside android/.
val sharedVectors: File = rootProject.file("../tests/fixtures/r7/phone_vectors.json")

tasks.named<Test>("test") {
    enabled = false // the tests run through jvmTests: no test framework (D24)
}

val jvmTests = tasks.register<JavaExec>("jvmTests") {
    description = "Runs core's JVM tests against the shared vectors (R7 D24)."
    group = "verification"
    dependsOn(tasks.named("testClasses"))
    classpath = sourceSets["test"].runtimeClasspath
    mainClass.set("io.github.shark2558.jarvis.core.CoreTestsKt")
    systemProperty("jarvis.vectors", sharedVectors.absolutePath)
}

tasks.named("check") {
    dependsOn(jvmTests)
}
