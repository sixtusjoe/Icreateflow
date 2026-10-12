package com.icreateflow.companion.data

import com.icreateflow.companion.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * The icreateflow API, as the phone uses it.
 *
 * Only endpoints that already exist and that the website already calls:
 * sign in, who am I, campaigns and their controls, and sending accounts. The app must not show anything
 * the backend cannot back up — the same honesty rule the website's
 * redesign runs on.
 */
object Api {
    /** The server — the build's default until the person picks another (`Session.server`). */
    @Volatile var base: String = BuildConfig.API_BASE

    /** Whether ICREATEFLOW answers at `server` — its public config needs no sign-in. */
    suspend fun reachable(server: String): Boolean = withContext(Dispatchers.IO) {
        runCatching {
            http.newCall(Request.Builder().url("$server/api/public/config").build()).execute().use { it.isSuccessful }
        }.getOrDefault(false)
    }

    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }
    private val http = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()

    class ApiError(val status: Int, message: String) : Exception(message)

    private suspend fun call(req: Request): String = withContext(Dispatchers.IO) {
        try {
            http.newCall(req).execute().use { res ->
                val body = res.body?.string().orEmpty()
                if (!res.isSuccessful) throw ApiError(res.code, detailOf(body) ?: "Request failed (${res.code})")
                body
            }
        } catch (e: IOException) {
            throw ApiError(0, "Can't reach ICREATEFLOW — check your connection")
        }
    }

    /**
     * FastAPI puts the reason in `detail`: a string, or — when a campaign
     * can't start — `{"errors": [...]}`, every reason at once.
     */
    private fun detailOf(body: String): String? = runCatching {
        val d = (json.parseToJsonElement(body) as? JsonObject)?.get("detail") ?: return null
        when (d) {
            is JsonPrimitive -> d.contentOrNull
            is JsonObject -> (d["errors"] as? JsonArray)
                ?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }?.joinToString("\n")
            else -> null
        }
    }.getOrNull()

    private fun get(path: String, token: String?) = Request.Builder().url(base + path).apply {
        if (token != null) header("Authorization", "Bearer $token")
    }.build()

    suspend fun login(email: String, password: String): Login {
        val payload = json.encodeToString(LoginBody.serializer(), LoginBody(email.trim(), password))
        val req = Request.Builder().url("$base/api/auth/login")
            .post(payload.toRequestBody("application/json".toMediaType())).build()
        return json.decodeFromString(Login.serializer(), call(req))
    }

    suspend fun me(token: String): User =
        json.decodeFromString(User.serializer(), call(get("/api/auth/me", token)))

    private fun post(path: String, body: String, token: String? = null) = Request.Builder().url(base + path)
        .post(body.toRequestBody("application/json".toMediaType())).apply {
            if (token != null) header("Authorization", "Bearer $token")
        }.build()

    /** New accounts wait for an admin, exactly as on the website. */
    suspend fun register(name: String, email: String, password: String): String {
        val body = json.encodeToString(RegisterBody.serializer(), RegisterBody(email.trim(), password, name.trim()))
        val out = json.decodeFromString(Registered.serializer(), call(post("/api/auth/register", body)))
        return out.message ?: "Your account is waiting for approval."
    }

    /** Always succeeds, whether or not the address has an account — the server does not say. */
    suspend fun forgotPassword(email: String) {
        call(post("/api/auth/forgot-password", json.encodeToString(EmailBody.serializer(), EmailBody(email.trim()))))
    }

    suspend fun resetPassword(email: String, code: String, newPassword: String) {
        call(post("/api/auth/reset-password",
            json.encodeToString(ResetBody.serializer(), ResetBody(email.trim(), code.trim(), newPassword))))
    }

    suspend fun campaign(token: String, id: Int): CampaignDetail =
        json.decodeFromString(CampaignDetail.serializer(), call(get("/api/outreach/campaigns/$id", token)))

    suspend fun targets(token: String, id: Int, status: String?, offset: Int, limit: Int = 50): TargetPage {
        val q = buildString {
            append("/api/outreach/campaigns/$id/targets?limit=$limit&offset=$offset")
            if (status != null) append("&status=$status")
        }
        return json.decodeFromString(TargetPage.serializer(), call(get(q, token)))
    }

    /** start / pause / resume / stop — the website's four run buttons. */
    suspend fun control(token: String, id: Int, action: String): Campaign =
        json.decodeFromString(Controlled.serializer(),
            call(post("/api/outreach/campaigns/$id/$action", "{}", token))).campaign

    suspend fun accounts(token: String): List<SendingAccount> =
        json.decodeFromString(kotlinx.serialization.builtins.ListSerializer(SendingAccount.serializer()),
            call(get("/api/outreach/accounts", token)))

    /** Clears an automatic pause — the website's "Clear error count". */
    suspend fun resumeAccount(token: String, id: Int): SendingAccount =
        json.decodeFromString(SendingAccount.serializer(),
            call(post("/api/outreach/accounts/$id/resume", "{}", token)))

    // --- the phone app: follows handed to this phone -----------------------

    suspend fun phoneAccounts(token: String, device: String): List<PhoneAccount> =
        json.decodeFromString(kotlinx.serialization.builtins.ListSerializer(PhoneAccount.serializer()),
            call(get("/api/outreach/companion/accounts?device_id=$device", token)))

    suspend fun linkPhone(token: String, device: String, accountId: Int, handle: String) {
        call(post("/api/outreach/companion/link",
            json.encodeToString(LinkBody.serializer(), LinkBody(device, accountId, handle)), token))
    }

    suspend fun unlinkPhone(token: String, device: String, accountId: Int) {
        call(post("/api/outreach/companion/unlink/$accountId",
            json.encodeToString(DeviceBody.serializer(), DeviceBody(device)), token))
    }

    /** The next follow for this phone, or null. Also tells the server the phone is on. */
    suspend fun nextTask(token: String, device: String): PhoneTask? =
        json.decodeFromString(NextTask.serializer(),
            call(post("/api/outreach/companion/next",
                json.encodeToString(DeviceBody.serializer(), DeviceBody(device)), token))).task

    suspend fun reportTask(token: String, device: String, id: Int, status: String, error: String?,
                           detail: Map<String, String>) {
        call(post("/api/outreach/companion/tasks/$id/result",
            json.encodeToString(ResultBody.serializer(), ResultBody(device, status, error, detail)), token))
    }

    suspend fun campaigns(token: String): List<Campaign> =
        json.decodeFromString(kotlinx.serialization.builtins.ListSerializer(Campaign.serializer()),
            call(get("/api/outreach/campaigns", token)))

    // --- lead discovery: the website's "Find profiles" ---------------------

    suspend fun leadAvailability(token: String, platform: String): LeadAvailability =
        json.decodeFromString(LeadAvailability.serializer(),
            call(get("/api/outreach/leads/availability?platform=$platform", token)))

    suspend fun startLeadSearch(token: String, campaignId: Int, body: LeadSearchBody): LeadRun =
        json.decodeFromString(LeadRun.serializer(),
            call(post("/api/outreach/campaigns/$campaignId/leads/search",
                json.encodeToString(LeadSearchBody.serializer(), body), token)))

    suspend fun leadSearch(token: String, searchId: Int): LeadSearchState =
        json.decodeFromString(LeadSearchState.serializer(),
            call(get("/api/outreach/leads/searches/$searchId", token)))

    suspend fun cancelLeadSearch(token: String, searchId: Int) {
        call(post("/api/outreach/leads/searches/$searchId/cancel", "{}", token))
    }

    suspend fun leads(token: String, searchId: Int): List<Lead> =
        json.decodeFromString(kotlinx.serialization.builtins.ListSerializer(Lead.serializer()),
            call(get("/api/outreach/leads/searches/$searchId/leads", token)))

    /** Found by earlier searches and in no campaign — searches skip them as already found. */
    suspend fun pendingLeads(token: String, platform: String): List<Lead> =
        json.decodeFromString(kotlinx.serialization.builtins.ListSerializer(Lead.serializer()),
            call(get("/api/outreach/leads/pending?platform=$platform", token)))

    suspend fun importLeads(token: String, campaignId: Int, leadIds: List<Int>, campaignIds: List<Int>): LeadImported =
        json.decodeFromString(LeadImported.serializer(),
            call(post("/api/outreach/campaigns/$campaignId/leads/import",
                json.encodeToString(LeadImportBody.serializer(),
                    LeadImportBody(leadIds, campaignIds.takeIf { it.isNotEmpty() })), token)))
}

@Serializable
data class LeadAvailability(
    val available: Boolean = false,
    @SerialName("unavailable_reason") val unavailableReason: String? = null,
    /** True only when no new search can start at all. */
    val busy: Boolean = false,
    @SerialName("busy_reason") val busyReason: String? = null,
    val accounts: List<DiscoveryAccount> = emptyList(),
    @SerialName("max_per_search") val maxPerSearch: Int = 300,
)

@Serializable
data class DiscoveryAccount(
    val id: Int,
    val name: String = "",
    @SerialName("used_today") val usedToday: Int = 0,
    val busy: Boolean = false,
)

@Serializable
data class LeadSearchBody(
    val niche: String = "",
    @SerialName("seed_accounts") val seedAccounts: String? = null,
    val location: String? = null,
    val interests: String? = null,
    val wanted: Int = 50,
    val platform: String,
    @SerialName("account_id") val accountId: Int? = null,
    @SerialName("include_commenters") val commenters: Boolean = true,
    @SerialName("include_likers") val likers: Boolean = false,
    @SerialName("include_replies") val replies: Boolean = true,
    @SerialName("enrich_profiles") val enrich: Boolean = false,
)

/** A search in progress, as the process running it reports it. */
@Serializable
data class LeadRun(
    @SerialName("search_id") val searchId: Int,
    val status: String = "queued",
    val message: String = "",
    val found: Int = 0,
    val wanted: Int = 0,
    val done: Boolean = false,
)

/** The search's own row — all there is once the process that ran it is gone. */
@Serializable
data class StoredSearch(
    val id: Int,
    val status: String = "queued",
    val message: String? = null,
    val found: Int? = null,
    val wanted: Int = 0,
)

@Serializable
data class LeadSearchState(
    val search: StoredSearch,
    val run: LeadRun? = null,
    val running: Boolean = false,
)

@Serializable
data class Lead(
    val id: Int,
    val username: String = "",
    val followers: Int? = null,
    @SerialName("profile_url") val profileUrl: String? = null,
    @SerialName("display_name") val displayName: String? = null,
    val bio: String? = null,
    val source: String? = null,
    val score: Int? = null,
    val reason: String? = null,
    @SerialName("imported_at") val importedAt: String? = null,
)

@Serializable
data class LeadImportBody(
    @SerialName("lead_ids") val leadIds: List<Int>,
    @SerialName("campaign_ids") val campaignIds: List<Int>? = null,
)

@Serializable
data class LeadImported(
    val ready: Int = 0,
    val campaigns: List<LeadImportedTo>? = null,
)

@Serializable
data class LeadImportedTo(
    @SerialName("campaign_id") val campaignId: Int,
    @SerialName("campaign_name") val campaignName: String = "",
    val ready: Int = 0,
)

@Serializable
data class LoginBody(val email: String, val password: String)

@Serializable
data class Login(val token: String, val user: User)

@Serializable
data class User(
    val id: Int = 0,
    val email: String = "",
    val name: String? = null,
    val role: String? = null,
)

@Serializable
data class Campaign(
    val id: Int,
    val name: String = "",
    val status: String = "draft",
    val activity: String = "message",
    val platform: String = "tiktok",
    @SerialName("total_targets") val totalTargets: Int = 0,
    @SerialName("processed_count") val processed: Int = 0,
    @SerialName("successful_count") val successful: Int = 0,
    @SerialName("failed_count") val failed: Int = 0,
    val progress: Double = 0.0,
    @SerialName("paused_until") val pausedUntil: String? = null,
    @SerialName("paused_reason") val pausedReason: String? = null,
    @SerialName("message_refused") val messageRefused: Boolean = false,
    /** What a message campaign sends, with {{placeholders}} still in it. */
    @SerialName("message_template") val messageTemplate: String? = null,
    @SerialName("has_attachment") val hasAttachment: Boolean = false,
    @SerialName("updated_at") val updatedAt: String? = null,
)

@Serializable
data class RegisterBody(val email: String, val password: String, val name: String)

@Serializable
data class Registered(val pending: Boolean = true, val message: String? = null)

@Serializable
data class EmailBody(val email: String)

@Serializable
data class ResetBody(val email: String, val code: String, @SerialName("new_password") val newPassword: String)

@Serializable
data class CampaignDetail(
    val campaign: Campaign,
    @SerialName("target_counts") val targetCounts: Map<String, Int> = emptyMap(),
    @SerialName("success_outcomes") val successOutcomes: Map<String, Int> = emptyMap(),
)

@Serializable
data class Target(
    val id: Int,
    val username: String = "",
    @SerialName("profile_url") val profileUrl: String? = null,
    val status: String = "queued",
    val attempts: Int = 0,
    @SerialName("error_message") val error: String? = null,
    @SerialName("sent_at") val sentAt: String? = null,
    @SerialName("last_attempt_at") val lastAttemptAt: String? = null,
)

@Serializable
data class TargetPage(
    val targets: List<Target> = emptyList(),
    val counts: Map<String, Int> = emptyMap(),
    val total: Int = 0,
)

@Serializable
data class Controlled(val campaign: Campaign)

@Serializable
data class SendingAccount(
    val id: Int,
    val name: String = "",
    val platform: String = "tiktok",
    val status: String = "idle",
    val enabled: Boolean = true,
    val purpose: String? = null,
    @SerialName("has_session") val hasSession: Boolean = false,
    @SerialName("session_reference") val sessionReference: String? = null,
    @SerialName("messages_processed") val processed: Int = 0,
    @SerialName("last_activity_at") val lastActivityAt: String? = null,
    @SerialName("consecutive_errors") val consecutiveErrors: Int = 0,
    @SerialName("last_error") val lastError: String? = null,
    @SerialName("paused_reason") val pausedReason: String? = null,
    @SerialName("device_handle") val deviceHandle: String? = null,
)

@Serializable
data class PhoneAccount(
    val id: Int,
    val name: String = "",
    val enabled: Boolean = true,
    val status: String = "idle",
    @SerialName("paused_reason") val pausedReason: String? = null,
    val handle: String? = null,
    /** "this", "other" (another phone), or null. */
    val linked: String? = null,
    @SerialName("seen_at") val seenAt: String? = null,
)

@Serializable
data class LinkBody(@SerialName("device_id") val deviceId: String, @SerialName("account_id") val accountId: Int,
                    val handle: String)

@Serializable
data class DeviceBody(@SerialName("device_id") val deviceId: String)

@Serializable
data class PhoneTask(
    val id: Int,
    /** "follow" or "message". */
    val action: String = "follow",
    val username: String = "",
    val handle: String = "",
    /** A message task's text, already written by the server. */
    val message: String? = null,
)

@Serializable
data class NextTask(val task: PhoneTask? = null)

@Serializable
data class ResultBody(
    @SerialName("device_id") val deviceId: String,
    val status: String,
    val error: String? = null,
    val detail: Map<String, String> = emptyMap(),
)
