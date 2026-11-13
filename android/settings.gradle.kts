// android/settings.gradle.kts -- R7 D23, D24: the Android project's settings (I0's first version;
// Part E's from here on). Two modules: `core` (plain Kotlin, tested on the JVM against the
// server's vectors) and `app` (the Trusted Web Activity and its few native parts). Libraries come
// only from Google's Maven and Maven Central, at the exact versions in gradle/libs.versions.toml.
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "jarvis-android"
include(":core", ":app")
