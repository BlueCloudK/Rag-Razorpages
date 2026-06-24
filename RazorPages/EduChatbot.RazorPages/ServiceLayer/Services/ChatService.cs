using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using DataAccessLayer.Data;
using DataAccessLayer.Models;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using ServiceLayer.Models;

namespace ServiceLayer.Services
{
    public class ChatService : IChatService
    {
        private readonly ApplicationDbContext _context;
        private readonly IHttpClientFactory _httpClientFactory;
        private readonly IAccessControlService _accessControl;
        private readonly ICurrentUserService _currentUser;
        private readonly ISubscriptionService _subscriptionService;
        private readonly IUsageService _usageService;
        private readonly UserManager<ApplicationUser> _userManager;
        private readonly IAuditLogService _auditLogService;
        private readonly IRealtimeNotificationService _realtime;

        public ChatService(
            ApplicationDbContext context,
            IHttpClientFactory httpClientFactory,
            IAccessControlService accessControl,
            ICurrentUserService currentUser,
            ISubscriptionService subscriptionService,
            IUsageService usageService,
            UserManager<ApplicationUser> userManager,
            IAuditLogService auditLogService,
            IRealtimeNotificationService realtime)
        {
            _context = context;
            _httpClientFactory = httpClientFactory;
            _accessControl = accessControl;
            _currentUser = currentUser;
            _subscriptionService = subscriptionService;
            _usageService = usageService;
            _userManager = userManager;
            _auditLogService = auditLogService;
            _realtime = realtime;
        }

        public async Task<ChatPageDto?> GetChatPageAsync(int subjectId, int? sessionId = null)
        {
            if (!await _accessControl.CanViewSubjectAsync(subjectId))
                return null;

            var userId = _currentUser.UserId;
            if (string.IsNullOrEmpty(userId))
                return null;

            var subject = await _context.Subjects.FindAsync(subjectId);
            if (subject == null)
                return null;

            var session = await FindSessionAsync(subjectId, userId, sessionId);

            var documents = await _context.Documents
                .Where(d => d.SubjectId == subjectId)
                .OrderByDescending(d => d.UploadedAt)
                .ToListAsync();

            var members = await _context.SubjectMemberships
                .Include(m => m.Subject)
                .Include(m => m.User)
                .Where(m => m.SubjectId == subjectId)
                .OrderBy(m => m.RoleInSubject)
                .ThenBy(m => m.User!.Email)
                .Select(m => new SubjectMembershipAdminDto
                {
                    Id = m.Id,
                    SubjectId = m.SubjectId,
                    UserId = m.UserId,
                    SubjectName = m.Subject!.Name,
                    UserEmail = m.User!.Email ?? "",
                    RoleInSubject = m.RoleInSubject,
                    IsCurrentUser = m.UserId == userId
                })
                .ToListAsync();

            foreach (var member in members)
            {
                var memberUser = await _userManager.FindByIdAsync(member.UserId);
                member.IsSystemAdmin = memberUser != null && await _userManager.IsInRoleAsync(memberUser, AuthConstants.Admin);
            }

            var availableMembers = await _context.OrganizationMembers
                .Include(m => m.User)
                .Where(m => m.OrganizationId == subject.OrganizationId)
                .Where(m => m.UserId != userId)
                .Where(m => !_context.SubjectMemberships.Any(sm =>
                    sm.SubjectId == subjectId &&
                    sm.UserId == m.UserId))
                .OrderBy(m => m.User!.Email)
                .Select(m => new SubjectMemberOptionDto
                {
                    UserId = m.UserId,
                    Email = m.User!.Email ?? ""
                })
                .ToListAsync();

            if (!await _currentUser.IsInRoleAsync(AuthConstants.Admin))
            {
                var filteredMembers = new List<SubjectMemberOptionDto>();
                foreach (var member in availableMembers)
                {
                    var memberUser = await _userManager.FindByIdAsync(member.UserId);
                    if (memberUser != null && !await _userManager.IsInRoleAsync(memberUser, AuthConstants.Admin))
                    {
                        filteredMembers.Add(member);
                    }
                }

                availableMembers = filteredMembers;
            }

            return new ChatPageDto
            {
                CurrentSubject = subject.ToDto(includeDocuments: false),
                CurrentSession = session?.ToDto(),
                ChatSessions = await GetSessionSummariesAsync(subjectId, userId, session?.Id),
                ActiveSessionId = session?.Id ?? 0,
                CurrentDocuments = documents.Select(d => d.ToDto(includeSubject: false)).ToList(),
                SubjectMembers = members,
                AvailableSubjectMembers = availableMembers,
                CanManageSubject = await _accessControl.CanManageSubjectAsync(subjectId),
                CanUploadDocuments = await _accessControl.CanUploadDocumentAsync(subjectId),
                CanDeleteDocuments = await _accessControl.CanDeleteDocumentAsync(subjectId),
                SubscriptionStatus = await _subscriptionService.GetCurrentStatusAsync()
            };
        }

        public async Task<ChatSendResult> SendMessageAsync(int subjectId, string content, int? sessionId = null, CancellationToken cancellationToken = default)
        {
            if (!await _accessControl.CanViewSubjectAsync(subjectId))
            {
                return new ChatSendResult { Success = false, StatusCode = 403, Message = "You do not have access to this subject." };
            }

            if (!await _subscriptionService.CanAskQuestionAsync())
            {
                return new ChatSendResult { Success = false, StatusCode = 429, Message = "Your daily question quota has been reached." };
            }

            if (string.IsNullOrWhiteSpace(content))
            {
                return new ChatSendResult { Success = false, StatusCode = 400, Message = "Please enter a question." };
            }

            var userId = _currentUser.UserId;
            if (string.IsNullOrEmpty(userId))
            {
                return new ChatSendResult { Success = false, StatusCode = 401, Message = "Please log in before chatting." };
            }

            var session = await FindSessionAsync(subjectId, userId, sessionId);

            if (session == null)
            {
                session = await CreateSessionEntityAsync(subjectId, userId);
            }

            var duplicateTurn = TryGetRecentCompletedTurn(session, content);
            if (duplicateTurn != null)
                return duplicateTurn;

            var indexedDocuments = await _context.Documents
                .Where(d => d.SubjectId == subjectId && d.IsIndexed)
                .Select(d => new { d.Id, d.FileName })
                .ToListAsync();

            var processingDocuments = await _context.Documents.CountAsync(d =>
                d.SubjectId == subjectId &&
                !d.IsIndexed &&
                d.IndexStatus != "Failed");

            if (!indexedDocuments.Any())
            {
                var waitMessage = processingDocuments > 0
                    ? $"Documents are still being indexed ({processingDocuments} file(s) processing). Wait until indexing completes before chatting."
                    : "This subject has no indexed documents yet. Upload documents and wait for indexing to complete.";

                return new ChatSendResult { Success = false, StatusCode = 409, Message = waitMessage };
            }

            var recentHistory = (session.Messages ?? Enumerable.Empty<ChatMessage>())
                .OrderBy(m => m.Timestamp)
                .TakeLast(6)
                .Select(m => new { role = m.Role, content = m.Content })
                .ToList();
            var subjectMemory = await BuildSubjectMemoryAsync(subjectId, userId, session.Id);

            var userMsg = new ChatMessage
            {
                SessionId = session.Id,
                Role = "User",
                Content = content,
                SourceDocuments = "",
                Timestamp = DateTime.UtcNow
            };

            string answer;
            string sourceDocs = "";
            ChatTraceDto trace = new();

            var documentFilters = indexedDocuments
                .Select(d => d.Id.ToString())
                .Concat(indexedDocuments.Select(d => d.FileName))
                .Where(value => !string.IsNullOrWhiteSpace(value))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList();

            try
            {
                var payload = new
                {
                    session_id = session.Id,
                    subject_id = subjectId,
                    query = content,
                    document_ids = documentFilters,
                    history = recentHistory,
                    subject_memory = subjectMemory
                };
                var json = JsonSerializer.Serialize(payload);
                using var stringContent = new StringContent(json, Encoding.UTF8, "application/json");
                using var client = _httpClientFactory.CreateClient("AiService");
                using var response = await client.PostAsync("/api/chat/ask", stringContent, cancellationToken);

                if (!response.IsSuccessStatusCode)
                    throw new HttpRequestException($"AI Engine returned HTTP {(int)response.StatusCode}.");

                var responseString = await response.Content.ReadAsStringAsync(cancellationToken);
                using var jsonDoc = JsonDocument.Parse(responseString);
                answer = jsonDoc.RootElement.GetProperty("answer").GetString() ?? "Empty response.";
                trace = ReadTrace(jsonDoc.RootElement);

                if (jsonDoc.RootElement.TryGetProperty("sources", out var sourcesEl))
                {
                    var sourcesList = sourcesEl.EnumerateArray()
                        .Select(s => s.GetString())
                        .Where(s => !string.IsNullOrEmpty(s));
                    sourceDocs = string.Join(", ", sourcesList);
                }
            }
            catch (OperationCanceledException)
            {
                return new ChatSendResult
                {
                    Success = false,
                    StatusCode = 499,
                    Message = "Request stopped."
                };
            }
            catch
            {
                return new ChatSendResult
                {
                    Success = false,
                    StatusCode = 503,
                    Message = "AI Engine is not ready or returned an error. Wait until AI is ready, then send again."
                };
            }

            var botMsg = new ChatMessage
            {
                SessionId = session.Id,
                Role = "Bot",
                Content = answer,
                SourceDocuments = sourceDocs,
                Timestamp = DateTime.UtcNow
            };

            _context.ChatMessages.Add(userMsg);
            _context.ChatMessages.Add(botMsg);
            await _context.SaveChangesAsync(cancellationToken);
            await _usageService.IncrementQuestionCountAsync();
            await _auditLogService.RecordAsync("AskQuestion", "ChatSession", session.Id, subjectId, null, "User asked a question in a subject chat.");

            return new ChatSendResult
            {
                Success = true,
                SessionId = session.Id,
                User = userMsg.ToDto(),
                Bot = botMsg.ToDto(),
                Trace = trace
            };
        }

        public async Task<ChatSendResult> SendMessageStreamAsync(int subjectId, string content, int? sessionId, Func<string, JsonElement, Task> onTraceEvent, CancellationToken cancellationToken = default)
        {
            if (!await _accessControl.CanViewSubjectAsync(subjectId))
                return new ChatSendResult { Success = false, StatusCode = 403, Message = "You do not have access to this subject." };

            if (!await _subscriptionService.CanAskQuestionAsync())
                return new ChatSendResult { Success = false, StatusCode = 429, Message = "Your daily question quota has been reached." };

            if (string.IsNullOrWhiteSpace(content))
                return new ChatSendResult { Success = false, StatusCode = 400, Message = "Please enter a question." };

            var userId = _currentUser.UserId;
            if (string.IsNullOrEmpty(userId))
                return new ChatSendResult { Success = false, StatusCode = 401, Message = "Please log in before chatting." };

            var session = await FindSessionAsync(subjectId, userId, sessionId) ?? await CreateSessionEntityAsync(subjectId, userId);

            var duplicateTurn = TryGetRecentCompletedTurn(session, content);
            if (duplicateTurn != null)
                return duplicateTurn;

            var indexedDocuments = await _context.Documents
                .Where(d => d.SubjectId == subjectId && d.IsIndexed)
                .Select(d => new { d.Id, d.FileName })
                .ToListAsync(cancellationToken);

            var processingDocuments = await _context.Documents.CountAsync(d =>
                d.SubjectId == subjectId &&
                !d.IsIndexed &&
                d.IndexStatus != "Failed",
                cancellationToken);

            if (!indexedDocuments.Any())
            {
                var waitMessage = processingDocuments > 0
                    ? $"Documents are still being indexed ({processingDocuments} file(s) processing). Wait until indexing completes before chatting."
                    : "This subject has no indexed documents yet. Upload documents and wait for indexing to complete.";

                return new ChatSendResult { Success = false, StatusCode = 409, Message = waitMessage };
            }

            var recentHistory = (session.Messages ?? Enumerable.Empty<ChatMessage>())
                .OrderBy(m => m.Timestamp)
                .TakeLast(6)
                .Select(m => new { role = m.Role, content = m.Content })
                .ToList();
            var subjectMemory = await BuildSubjectMemoryAsync(subjectId, userId, session.Id);

            var userMsg = new ChatMessage
            {
                SessionId = session.Id,
                Role = "User",
                Content = content,
                SourceDocuments = "",
                Timestamp = DateTime.UtcNow
            };

            string finalJson = "";

            var documentFilters = indexedDocuments
                .Select(d => d.Id.ToString())
                .Concat(indexedDocuments.Select(d => d.FileName))
                .Where(value => !string.IsNullOrWhiteSpace(value))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList();

            try
            {
                var payload = new
                {
                    session_id = session.Id,
                    subject_id = subjectId,
                    query = content,
                    document_ids = documentFilters,
                    history = recentHistory,
                    subject_memory = subjectMemory
                };

                using var request = new HttpRequestMessage(HttpMethod.Post, "/api/chat/ask-stream")
                {
                    Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json")
                };
                using var client = _httpClientFactory.CreateClient("AiService");
                using var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);

                if (!response.IsSuccessStatusCode)
                    throw new HttpRequestException($"AI Engine returned HTTP {(int)response.StatusCode}.");

                await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken);
                using var reader = new StreamReader(stream, Encoding.UTF8);

                var eventName = "message";
                var dataBuilder = new StringBuilder();

                async Task DispatchAsync()
                {
                    if (dataBuilder.Length == 0)
                        return;

                    var data = dataBuilder.ToString();
                    dataBuilder.Clear();
                    try
                    {
                        using var jsonDoc = JsonDocument.Parse(data);
                        var payloadElement = jsonDoc.RootElement.Clone();
                        if (eventName == "final")
                        {
                            finalJson = data;
                        }
                        else if (eventName == "error")
                        {
                            await onTraceEvent("trace", payloadElement);
                        }
                        else
                        {
                            await onTraceEvent(eventName, payloadElement);
                        }
                    }
                    catch
                    {
                        // Streaming trace is best-effort; final response handling still decides success.
                    }
                    finally
                    {
                        eventName = "message";
                    }
                }

                while (!reader.EndOfStream && !cancellationToken.IsCancellationRequested)
                {
                    var line = await reader.ReadLineAsync(cancellationToken);
                    if (line == null)
                        break;

                    if (line.Length == 0)
                    {
                        await DispatchAsync();
                        continue;
                    }

                    if (line.StartsWith("event:", StringComparison.OrdinalIgnoreCase))
                    {
                        eventName = line["event:".Length..].Trim();
                    }
                    else if (line.StartsWith("data:", StringComparison.OrdinalIgnoreCase))
                    {
                        if (dataBuilder.Length > 0)
                            dataBuilder.AppendLine();
                        dataBuilder.Append(line["data:".Length..].TrimStart());
                    }
                }

                await DispatchAsync();
            }
            catch (OperationCanceledException)
            {
                return new ChatSendResult { Success = false, StatusCode = 499, Message = "Request stopped." };
            }
            catch
            {
                return new ChatSendResult
                {
                    Success = false,
                    StatusCode = 503,
                    Message = "AI Engine is not ready or returned an error. Wait until AI is ready, then send again."
                };
            }

            if (string.IsNullOrWhiteSpace(finalJson))
            {
                return new ChatSendResult { Success = false, StatusCode = 503, Message = "AI Engine did not return a final answer." };
            }

            string answer;
            string sourceDocs = "";
            ChatTraceDto trace;
            using (var jsonDoc = JsonDocument.Parse(finalJson))
            {
                answer = jsonDoc.RootElement.GetProperty("answer").GetString() ?? "Empty response.";
                trace = ReadTrace(jsonDoc.RootElement);
                if (jsonDoc.RootElement.TryGetProperty("sources", out var sourcesEl) && sourcesEl.ValueKind == JsonValueKind.Array)
                {
                    sourceDocs = string.Join(", ", sourcesEl.EnumerateArray()
                        .Select(s => s.GetString())
                        .Where(s => !string.IsNullOrEmpty(s)));
                }
            }

            var botMsg = new ChatMessage
            {
                SessionId = session.Id,
                Role = "Bot",
                Content = answer,
                SourceDocuments = sourceDocs,
                Timestamp = DateTime.UtcNow
            };

            _context.ChatMessages.Add(userMsg);
            _context.ChatMessages.Add(botMsg);
            await _context.SaveChangesAsync(cancellationToken);
            await _usageService.IncrementQuestionCountAsync();
            await _auditLogService.RecordAsync("AskQuestion", "ChatSession", session.Id, subjectId, null, "User asked a question in a subject chat.");

            return new ChatSendResult
            {
                Success = true,
                SessionId = session.Id,
                User = userMsg.ToDto(),
                Bot = botMsg.ToDto(),
                Trace = trace
            };
        }

        private static ChatTraceDto ReadTrace(JsonElement root)
        {
            var trace = new ChatTraceDto
            {
                Model = ReadString(root, "model"),
                RetrievalStrategy = ReadString(root, "retrieval_strategy"),
                Confidence = ReadDouble(root, "confidence"),
                FallbackUsed = ReadBool(root, "fallback_used")
            };

            if (root.TryGetProperty("processing_trace", out var processingTrace))
            {
                trace.ProcessingTrace = processingTrace.Clone();
            }

            if (!root.TryGetProperty("contexts", out var contextsEl) || contextsEl.ValueKind != JsonValueKind.Array)
                return trace;

            foreach (var item in contextsEl.EnumerateArray().Take(8))
            {
                trace.Contexts.Add(new ChatContextDto
                {
                    Content = ReadString(item, "content"),
                    Source = ReadString(item, "source"),
                    Similarity = ReadDouble(item, "similarity"),
                    ChunkIndex = ReadNullableInt(item, "chunk_index"),
                    PageNumber = ReadNullableInt(item, "page_number"),
                    ChapterNumber = ReadNullableInt(item, "chapter_number"),
                    Heading = ReadString(item, "heading"),
                    SectionPath = ReadString(item, "section_path"),
                    SourceVariant = ReadString(item, "source_variant")
                });
            }

            return trace;
        }

        private static string ReadString(JsonElement element, string name)
        {
            return element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
                ? value.GetString() ?? string.Empty
                : string.Empty;
        }

        private static double ReadDouble(JsonElement element, string name)
        {
            if (!element.TryGetProperty(name, out var value))
                return 0;

            if (value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out var number))
                return number;

            return 0;
        }

        private static bool ReadBool(JsonElement element, string name)
        {
            return element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.True;
        }

        private static int? ReadNullableInt(JsonElement element, string name)
        {
            if (!element.TryGetProperty(name, out var value))
                return null;

            if (value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number))
                return number;

            return null;
        }

        public async Task<int?> CreateSessionAsync(int subjectId)
        {
            if (!await _accessControl.CanViewSubjectAsync(subjectId))
                return null;

            var userId = _currentUser.UserId;
            if (string.IsNullOrEmpty(userId))
                return null;

            var subjectExists = await _context.Subjects.AnyAsync(s => s.Id == subjectId);
            if (!subjectExists)
                return null;

            var session = await CreateSessionEntityAsync(subjectId, userId);
            return session.Id;
        }

        public async Task<bool> DeleteSessionAsync(int subjectId, int sessionId)
        {
            if (!await _accessControl.CanViewSubjectAsync(subjectId))
                return false;

            var userId = _currentUser.UserId;
            if (string.IsNullOrEmpty(userId))
                return false;

            var session = await _context.ChatSessions
                .Include(s => s.Messages)
                .FirstOrDefaultAsync(s => s.Id == sessionId && s.SubjectId == subjectId && s.UserId == userId);

            if (session == null)
                return false;

            if (session.Messages?.Any() == true)
                _context.ChatMessages.RemoveRange(session.Messages);

            _context.ChatSessions.Remove(session);
            await _context.SaveChangesAsync();
            return true;
        }

        public async Task<bool> AddSubjectMemberAsync(int subjectId, string userId, string roleInSubject)
        {
            if (!await _accessControl.CanManageSubjectAsync(subjectId))
                return false;

            if (string.IsNullOrEmpty(userId) || userId == _currentUser.UserId)
                return false;

            var targetUser = await _userManager.FindByIdAsync(userId);
            if (targetUser == null)
                return false;

            var targetIsAdmin = await _userManager.IsInRoleAsync(targetUser, AuthConstants.Admin);
            var currentUserIsAdmin = await _currentUser.IsInRoleAsync(AuthConstants.Admin);
            if (targetIsAdmin && !currentUserIsAdmin)
                return false;

            roleInSubject = await ResolveSubjectRoleAsync(targetUser, roleInSubject, currentUserIsAdmin);
            if (string.IsNullOrEmpty(roleInSubject))
                return false;

            var subject = await _context.Subjects.FindAsync(subjectId);
            if (subject == null)
                return false;

            var belongsToOrganization = await _context.OrganizationMembers.AnyAsync(m =>
                m.OrganizationId == subject.OrganizationId &&
                m.UserId == userId);
            if (!belongsToOrganization)
                return false;

            var exists = await _context.SubjectMemberships.AnyAsync(m =>
                m.SubjectId == subjectId &&
                m.UserId == userId);
            if (exists)
                return false;

            if (roleInSubject == AuthConstants.SubjectLead)
                await DemoteExistingSubjectLeadAsync(subjectId);

            _context.SubjectMemberships.Add(new SubjectMembership
            {
                SubjectId = subjectId,
                UserId = userId,
                RoleInSubject = roleInSubject
            });
            await _context.SaveChangesAsync();
            await _auditLogService.RecordAsync("AddMember", "SubjectMembership", null, subjectId, null, $"Added {targetUser.Email} as {roleInSubject}.");
            await _realtime.MembershipChangedAsync("added", subjectId, userId);
            return true;
        }

        public async Task<bool> UpdateSubjectMemberRoleAsync(int subjectId, int membershipId, string roleInSubject)
        {
            if (!await _accessControl.CanManageSubjectAsync(subjectId))
                return false;

            var currentUserIsAdmin = await _currentUser.IsInRoleAsync(AuthConstants.Admin);
            if (!currentUserIsAdmin)
                return false;

            var membership = await _context.SubjectMemberships
                .Include(m => m.User)
                .FirstOrDefaultAsync(m => m.Id == membershipId && m.SubjectId == subjectId);
            if (membership == null || membership.User == null)
                return false;

            if (await _userManager.IsInRoleAsync(membership.User, AuthConstants.Admin))
                return false;

            var resolvedRole = await ResolveSubjectRoleAsync(membership.User, roleInSubject, currentUserIsAdmin);
            if (string.IsNullOrEmpty(resolvedRole) || membership.RoleInSubject == resolvedRole)
                return false;

            if (resolvedRole == AuthConstants.SubjectLead)
                await DemoteExistingSubjectLeadAsync(subjectId, membership.Id);

            membership.RoleInSubject = resolvedRole;
            await _context.SaveChangesAsync();
            await _auditLogService.RecordAsync("UpdateMemberRole", "SubjectMembership", membership.Id, subjectId, null, $"Updated subject membership for {membership.User.Email} to {resolvedRole}.");
            await _realtime.MembershipChangedAsync("updated", subjectId, membership.UserId);
            return true;
        }

        public async Task<bool> RemoveSubjectMemberAsync(int subjectId, int membershipId)
        {
            if (!await _accessControl.CanManageSubjectAsync(subjectId))
                return false;

            var membership = await _context.SubjectMemberships
                .FirstOrDefaultAsync(m => m.Id == membershipId && m.SubjectId == subjectId);
            if (membership == null)
                return false;

            if (membership.UserId == _currentUser.UserId)
                return false;

            var currentUserIsAdmin = await _currentUser.IsInRoleAsync(AuthConstants.Admin);
            if (membership.RoleInSubject == AuthConstants.SubjectLead && !currentUserIsAdmin)
                return false;

            var targetUser = await _userManager.FindByIdAsync(membership.UserId);
            var targetIsAdmin = targetUser != null && await _userManager.IsInRoleAsync(targetUser, AuthConstants.Admin);
            if (targetIsAdmin && !currentUserIsAdmin)
                return false;

            _context.SubjectMemberships.Remove(membership);
            await _context.SaveChangesAsync();
            await _auditLogService.RecordAsync("RemoveMember", "SubjectMembership", membership.Id, subjectId, null, $"Removed subject membership for {targetUser?.Email ?? membership.UserId}.");
            await _realtime.MembershipChangedAsync("removed", subjectId, membership.UserId);
            return true;
        }

        private async Task<string> ResolveSubjectRoleAsync(ApplicationUser targetUser, string requestedRole, bool currentUserIsAdmin)
        {
            var targetIsLecturer = await _userManager.IsInRoleAsync(targetUser, AuthConstants.Lecturer);
            var targetIsStudent = await _userManager.IsInRoleAsync(targetUser, AuthConstants.Student);

            if (requestedRole == AuthConstants.SubjectLead)
                return currentUserIsAdmin && targetIsLecturer ? AuthConstants.SubjectLead : string.Empty;

            if (requestedRole == AuthConstants.Lecturer)
                return targetIsLecturer ? AuthConstants.Lecturer : string.Empty;

            if (requestedRole == AuthConstants.Student)
                return targetIsStudent ? AuthConstants.Student : string.Empty;

            if (targetIsLecturer)
                return AuthConstants.Lecturer;

            return targetIsStudent ? AuthConstants.Student : string.Empty;
        }

        private async Task DemoteExistingSubjectLeadAsync(int subjectId, int? exceptMembershipId = null)
        {
            var currentLeads = await _context.SubjectMemberships
                .Where(m => m.SubjectId == subjectId && m.RoleInSubject == AuthConstants.SubjectLead)
                .Where(m => exceptMembershipId == null || m.Id != exceptMembershipId)
                .ToListAsync();

            foreach (var currentLead in currentLeads)
            {
                currentLead.RoleInSubject = AuthConstants.Lecturer;
            }
        }

        private async Task<ChatSession?> FindSessionAsync(int subjectId, string userId, int? sessionId)
        {
            if (sessionId.HasValue && sessionId.Value > 0)
            {
                return await _context.ChatSessions
                    .Include(s => s.Subject)
                    .Include(s => s.Messages)
                    .FirstOrDefaultAsync(s => s.Id == sessionId.Value && s.SubjectId == subjectId && s.UserId == userId);
            }

            var sessions = await _context.ChatSessions
                .Include(s => s.Messages)
                .Where(s => s.SubjectId == subjectId && s.UserId == userId)
                .ToListAsync();

            var selectedId = sessions
                .OrderByDescending(s => (s.Messages ?? new List<ChatMessage>()).Select(m => (DateTime?)m.Timestamp).Max() ?? s.CreatedAt)
                .ThenByDescending(s => s.CreatedAt)
                .Select(s => s.Id)
                .FirstOrDefault();

            if (selectedId == 0)
                return null;

            return await _context.ChatSessions
                .Include(s => s.Subject)
                .Include(s => s.Messages)
                .FirstAsync(s => s.Id == selectedId);
        }

        private async Task<ChatSession> CreateSessionEntityAsync(int subjectId, string userId)
        {
            var session = new ChatSession
            {
                SubjectId = subjectId,
                UserId = userId,
                CreatedAt = DateTime.UtcNow,
                Messages = new List<ChatMessage>()
            };
            _context.ChatSessions.Add(session);
            await _context.SaveChangesAsync();

            return await _context.ChatSessions
                .Include(s => s.Subject)
                .Include(s => s.Messages)
                .FirstAsync(s => s.Id == session.Id);
        }

        private static ChatSendResult? TryGetRecentCompletedTurn(ChatSession session, string content)
        {
            var normalizedContent = (content ?? string.Empty).Trim();
            if (string.IsNullOrEmpty(normalizedContent) || session.Messages == null)
                return null;

            var cutoff = DateTime.UtcNow.AddSeconds(-90);
            var orderedMessages = session.Messages
                .OrderBy(m => m.Timestamp)
                .ToList();

            for (var index = orderedMessages.Count - 1; index >= 0; index--)
            {
                var message = orderedMessages[index];
                if (!string.Equals(message.Role, "User", StringComparison.OrdinalIgnoreCase))
                    continue;

                if (message.Timestamp < cutoff)
                    break;

                if (!string.Equals((message.Content ?? string.Empty).Trim(), normalizedContent, StringComparison.Ordinal))
                    continue;

                var bot = orderedMessages
                    .Skip(index + 1)
                    .FirstOrDefault(m => string.Equals(m.Role, "Bot", StringComparison.OrdinalIgnoreCase));

                if (bot == null)
                    return null;

                return new ChatSendResult
                {
                    Success = true,
                    SessionId = session.Id,
                    User = message.ToDto(),
                    Bot = bot.ToDto(),
                    Trace = new ChatTraceDto()
                };
            }

            return null;
        }

        private async Task<List<ChatSessionSummaryDto>> GetSessionSummariesAsync(int subjectId, string userId, int? activeSessionId)
        {
            var sessions = await _context.ChatSessions
                .Include(s => s.Messages)
                .Where(s => s.SubjectId == subjectId && s.UserId == userId)
                .ToListAsync();

            return sessions
                .Select(s =>
                {
                    var messages = (s.Messages ?? new List<ChatMessage>()).OrderBy(m => m.Timestamp).ToList();
                    var firstUserMessage = messages.FirstOrDefault(m => m.Role == "User")?.Content;
                    var lastMessage = messages.LastOrDefault();
                    return new ChatSessionSummaryDto
                    {
                        Id = s.Id,
                        SubjectId = s.SubjectId,
                        Title = BuildSessionTitle(firstUserMessage, s.CreatedAt),
                        CreatedAt = s.CreatedAt,
                        LastMessageAt = lastMessage?.Timestamp,
                        LastMessagePreview = BuildPreview(lastMessage?.Content),
                        MessageCount = messages.Count,
                        IsActive = activeSessionId.HasValue && s.Id == activeSessionId.Value
                    };
                })
                .OrderByDescending(s => s.LastMessageAt ?? s.CreatedAt)
                .ThenByDescending(s => s.CreatedAt)
                .ToList();
        }

        private async Task<string> BuildSubjectMemoryAsync(int subjectId, string userId, int currentSessionId)
        {
            const int maxMessages = 12;
            const int maxMessageLength = 600;
            const int maxMemoryLength = 6000;

            var previousMessages = await _context.ChatMessages
                .Where(m =>
                    m.Session != null &&
                    m.Session.SubjectId == subjectId &&
                    m.Session.UserId == userId &&
                    m.SessionId != currentSessionId)
                .OrderByDescending(m => m.Timestamp)
                .Take(maxMessages)
                .Select(m => new { m.Role, m.Content })
                .ToListAsync();

            previousMessages.Reverse();
            var lines = previousMessages.Select(m =>
            {
                var message = m.Content.Trim().Replace("\r", " ").Replace("\n", " ");
                if (message.Length > maxMessageLength)
                    message = message[..maxMessageLength] + "...";
                return $"{m.Role}: {message}";
            });

            var content = string.Join(Environment.NewLine, lines);
            if (content.Length > maxMemoryLength)
                content = content[^maxMemoryLength..];

            var memory = await _context.SubjectUserMemories
                .FirstOrDefaultAsync(m => m.SubjectId == subjectId && m.UserId == userId);

            if (memory == null)
            {
                if (string.IsNullOrWhiteSpace(content))
                    return string.Empty;

                memory = new SubjectUserMemory
                {
                    SubjectId = subjectId,
                    UserId = userId,
                    Content = content,
                    UpdatedAt = DateTime.UtcNow
                };
                _context.SubjectUserMemories.Add(memory);
            }
            else
            {
                memory.Content = content;
                memory.UpdatedAt = DateTime.UtcNow;
            }

            await _context.SaveChangesAsync();
            return content;
        }

        private static string BuildSessionTitle(string? firstUserMessage, DateTime createdAt)
        {
            if (string.IsNullOrWhiteSpace(firstUserMessage))
                return $"New chat {createdAt.ToLocalTime():dd/MM HH:mm}";

            var title = firstUserMessage.Trim();
            return title.Length <= 42 ? title : title[..42] + "...";
        }

        private static string BuildPreview(string? content)
        {
            if (string.IsNullOrWhiteSpace(content))
                return "No messages yet.";

            var preview = content.Trim().Replace(Environment.NewLine, " ");
            return preview.Length <= 54 ? preview : preview[..54] + "...";
        }
    }
}
