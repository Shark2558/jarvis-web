// android/app/build.gradle.kts -- R7 D1, D22, D23: the JARVIS app. Its main screen is the console in
// the phone's browser, full screen (a Trusted Web Activity through android-browser-helper); beside
// it a few native parts: the Talk and SOS tiles, the notification service, the set-up screen, the
// Health Connect reader, the SOS screen and the folder watcher. Views and XML; Kotlin compiled by
// the Android Gradle plugin itself (built-in Kotlin, AGP 9).
//
// The JARVIS address is `jarvis.host`, read from the git-ignored android/local.properties (the
// Workshop writes it on the owner's laptop) or from `-Pjarvis.host=` (CI passes the placeholder
// jarvis.invalid). It is never written in this repository. The `personal` build type is the app
// the owner installs: not debuggable, signed with the debug key Android Studio made on his laptop.
import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
}

val placeholderHost = "jarvis.invalid"
val hostShape = Regex("[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+")

val localProperties = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.isFile) file.inputStream().use { load(it) }
}
val givenHost: String =
    ((findProperty("jarvis.host") as String?) ?: localProperties.getProperty("jarvis.host") ?: "").trim()
if (givenHost.isNotEmpty() && !hostShape.matches(givenHost)) {
    throw GradleException(
        "jarvis.host in android/local.properties must be a plain address such as " +
            "jarvis.example.com, Sir: no https:// and no slash.",
    )
}
val buildHost: String = givenHost.ifEmpty { placeholderHost }

val appVersion = Properties().apply {
    rootProject.file("version.properties").inputStream().use { load(it) }
}

// The app's own half of the site-and-app link (D4), and the web share target (D15). Android
// string resources drop plain double quotes, so the JSON's quotes are written as \".
fun assetStatements(host: String): String =
    """[{\"relation\":[\"delegate_permission/common.handle_all_urls\"],""" +
        """\"target\":{\"namespace\":\"web\",\"site\":\"https://$host\"}}]"""

fun shareTarget(host: String): String =
    """{\"action\":\"https://$host/app/share/in\",\"method\":\"POST\",""" +
        """\"enctype\":\"multipart/form-data\",\"params\":{\"title\":\"title\",\"text\":\"text\",""" +
        """\"url\":\"url\",\"files\":[{\"name\":\"files\",\"accept\":[\"image/jpeg\",""" +
        """\"image/png\",\"image/webp\",\"application/pdf\"]}]}}"""

android {
    namespace = "io.github.shark2558.jarvis"
    compileSdk = 36

    defaultConfig {
        applicationId = "io.github.shark2558.jarvis"
        minSdk = 28
        targetSdk = 36
        versionCode = appVersion.getProperty("versionCode").trim().toInt()
        versionName = appVersion.getProperty("versionName").trim()
        manifestPlaceholders["jarvisHost"] = buildHost
        buildConfigField("String", "JARVIS_HOST", "\"$buildHost\"")
        resValue("string", "asset_statements", assetStatements(buildHost))
        resValue("string", "share_target", shareTarget(buildHost))
    }

    buildTypes {
        create("personal") {
            isDebuggable = false
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("debug")
            matchingFallbacks += listOf("release")
        }
    }

    buildFeatures {
        buildConfig = true
        resValues = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    lint {
        abortOnError = true
        checkReleaseBuilds = true
        textReport = true
        textOutput = file("stdout")
    }
}

// Kotlin writes Java 17 bytecode, as the Java compiler does (one JVM target for both).
tasks.withType<org.jetbrains.kotlin.gradle.tasks.KotlinCompile>().configureEach {
    compilerOptions.jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
}

// A `personal` build with no address stops with one plain line (D23).
val checkJarvisHost = tasks.register("checkJarvisHost") {
    val given = givenHost
    doLast {
        if (given.isEmpty()) {
            throw GradleException(
                "Please add the line jarvis.host=<your JARVIS address> to android/local.properties, Sir.",
            )
        }
    }
}
tasks.matching { it.name == "prePersonalBuild" }.configureEach {
    dependsOn(checkJarvisHost)
}

dependencies {
    implementation(project(":core"))
    implementation(libs.androidbrowserhelper)
    implementation(libs.androidx.browser)
    implementation(libs.androidx.core)
    implementation(libs.androidx.work.runtime)
    implementation(libs.health.connect.client)
}
