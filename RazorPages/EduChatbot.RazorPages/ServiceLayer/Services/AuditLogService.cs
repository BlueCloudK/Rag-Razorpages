using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using DataAccessLayer.Data;
using DataAccessLayer.Models;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using ServiceLayer.Models;

namespace ServiceLayer.Services
{
    public class AuditLogService : IAuditLogService
    {
        private readonly ApplicationDbContext _context;
        private readonly ICurrentUserService _currentUser;
        private readonly UserManager<ApplicationUser> _userManager;

        public AuditLogService(ApplicationDbContext context, ICurrentUserService currentUser, UserManager<ApplicationUser> userManager)
        {
            _context = context;
            _currentUser = currentUser;
            _userManager = userManager;
        }

        public async Task RecordAsync(string action, string entityType, int? entityId = null, int? subjectId = null, int? organizationId = null, string? summary = null)
        {
            var user = await _currentUser.GetCurrentUserAsync();
            var roles = user == null ? Array.Empty<string>() : await _userManager.GetRolesAsync(user);
            await RecordForUserAsync(user?.Id, user?.Email ?? "system", roles.FirstOrDefault(), action, entityType, entityId, subjectId, organizationId, summary);
        }

        public async Task RecordForUserAsync(string? actorUserId, string actorEmail, string? actorRole, string action, string entityType, int? entityId = null, int? subjectId = null, int? organizationId = null, string? summary = null)
        {
            if (!organizationId.HasValue && subjectId.HasValue)
            {
                organizationId = await _context.Subjects
                    .Where(s => s.Id == subjectId.Value)
                    .Select(s => s.OrganizationId)
                    .FirstOrDefaultAsync();
            }

            _context.AuditLogs.Add(new AuditLog
            {
                ActorUserId = actorUserId,
                ActorEmail = string.IsNullOrWhiteSpace(actorEmail) ? "system" : actorEmail,
                ActorRole = string.IsNullOrWhiteSpace(actorRole) ? "Unknown" : actorRole,
                Action = action,
                EntityType = entityType,
                EntityId = entityId,
                SubjectId = subjectId,
                OrganizationId = organizationId,
                Summary = Trim(summary ?? $"{action} {entityType}", 500),
                CreatedAt = DateTime.UtcNow
            });

            await _context.SaveChangesAsync();
        }

        public async Task<List<AuditLogDto>> GetRecentLogsAsync(int take = 80)
        {
            var query = _context.AuditLogs.AsQueryable();
            if (!await _currentUser.IsInRoleAsync(AuthConstants.Admin))
            {
                var lecturerSubjectIds = await GetLecturerSubjectIdsAsync();
                query = query.Where(l => l.SubjectId.HasValue && lecturerSubjectIds.Contains(l.SubjectId.Value));
            }

            return await query
                .OrderByDescending(l => l.CreatedAt)
                .Take(Math.Clamp(take, 10, 200))
                .Select(l => new AuditLogDto
                {
                    Id = l.Id,
                    ActorEmail = l.ActorEmail,
                    ActorRole = l.ActorRole,
                    Action = l.Action,
                    EntityType = l.EntityType,
                    EntityId = l.EntityId,
                    SubjectId = l.SubjectId,
                    OrganizationId = l.OrganizationId,
                    Summary = l.Summary,
                    CreatedAt = l.CreatedAt
                })
                .ToListAsync();
        }

        public async Task<List<SubjectUsageDto>> GetSubjectUsageAsync()
        {
            var subjectsQuery = _context.Subjects.AsQueryable();
            if (!await _currentUser.IsInRoleAsync(AuthConstants.Admin))
            {
                if (!await _currentUser.IsInRoleAsync(AuthConstants.Lecturer))
                    return new List<SubjectUsageDto>();

                var lecturerSubjectIds = await GetLecturerSubjectIdsAsync();
                subjectsQuery = subjectsQuery.Where(s => lecturerSubjectIds.Contains(s.Id));
            }

            var subjects = await subjectsQuery
                .OrderBy(s => s.Name)
                .Select(s => new { s.Id, s.Name, s.Code })
                .ToListAsync();

            var subjectIds = subjects.Select(s => s.Id).ToList();
            if (!subjectIds.Any())
                return new List<SubjectUsageDto>();

            var questions = await _context.ChatMessages
                .Where(m => m.Role == "User" && m.Session != null && subjectIds.Contains(m.Session.SubjectId))
                .GroupBy(m => m.Session!.SubjectId)
                .Select(g => new
                {
                    SubjectId = g.Key,
                    QuestionCount = g.Count(),
                    SessionCount = g.Select(m => m.SessionId).Distinct().Count(),
                    LastAskedAt = g.Max(m => (DateTime?)m.Timestamp)
                })
                .ToListAsync();

            return subjects
                .Select(subject =>
                {
                    var usage = questions.FirstOrDefault(q => q.SubjectId == subject.Id);
                    return new SubjectUsageDto
                    {
                        SubjectId = subject.Id,
                        SubjectName = subject.Name,
                        SubjectCode = subject.Code,
                        QuestionCount = usage?.QuestionCount ?? 0,
                        SessionCount = usage?.SessionCount ?? 0,
                        LastAskedAt = usage?.LastAskedAt
                    };
                })
                .OrderByDescending(s => s.QuestionCount)
                .ThenBy(s => s.SubjectName)
                .ToList();
        }

        private async Task<List<int>> GetLecturerSubjectIdsAsync()
        {
            var userId = _currentUser.UserId;
            if (string.IsNullOrEmpty(userId))
                return new List<int>();

            return await _context.SubjectMemberships
                .Where(m => m.UserId == userId && m.RoleInSubject == AuthConstants.Lecturer)
                .Select(m => m.SubjectId)
                .Distinct()
                .ToListAsync();
        }

        private static string Trim(string value, int maxLength)
        {
            return value.Length <= maxLength ? value : value[..maxLength];
        }
    }
}
