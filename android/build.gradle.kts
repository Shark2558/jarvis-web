// android/build.gradle.kts -- R7 D23: the pinned plugins, declared once and applied by `core` and
// `app`. `resolveDependencies` (one in each project, so each resolves only its own
// configurations) resolves every compile and runtime classpath before anything is built, so CI's
// first step proves each pinned library exists on Google's Maven or Maven Central.
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.jvm) apply false
}

allprojects {
    val owner = this
    tasks.register("resolveDependencies") {
        notCompatibleWithConfigurationCache("resolves this project's classpaths on purpose")
        doLast {
            val wanted = owner.configurations.filter {
                it.isCanBeResolved &&
                    (it.name.endsWith("CompileClasspath") || it.name.endsWith("RuntimeClasspath"))
            }
            wanted.forEach { it.resolve() }
            println("${owner.path}: ${wanted.size} classpaths resolved")
        }
    }
}
