using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using DataAccessLayer.Data;
using DataAccessLayer.Models;
using Microsoft.EntityFrameworkCore;
using ServiceLayer.Models;

namespace ServiceLayer.Services
{
    public class SubjectService : ISubjectService
    {
        private readonly ApplicationDbContext _context;
        private readonly IAccessControlService _accessControl;
        private readonly ICurrentUserService _currentUser;
        private readonly ISubscriptionService _subscriptionService;
        private readonly IAuditLogService _auditLogService;
        private readonly IRealtimeNotificationService _realtime;

        public SubjectService(
            ApplicationDbContext context,
            IAccessControlService accessControl,
            ICurrentUserService currentUser,
            ISubscriptionService subscriptionService,
            IAuditLogService auditLogService,
            IRealtimeNotificationService realtime)
        {
            _context = context;
            _accessControl = accessControl;
            _currentUser = currentUser;
            _subscriptionService = subscriptionService;
            _auditLogService = auditLogService;
            _realtime = realtime;
        }

        public async Task<List<SubjectDto>> GetAllAsync(bool includeDocuments = false)
        {
            IQueryable<Subject> query = _context.Subjects;
            if (includeDocuments)
            {
                query = query.Include(s => s.Documents).Include(s => s.Organization);
            }
            else
            {
                query = query.Include(s => s.Organization);
            }

            if (!await _accessControl.IsAdminAsync())
            {
                var userId = _currentUser.UserId;
                query = query.Where(s => _context.SubjectMemberships.Any(m => m.SubjectId == s.Id && m.UserId == userId));
            }

            var subjects = await query
                .OrderBy(s => s.Name)
                .Select(s => s.ToDto(includeDocuments))
                .ToListAsync();

            if (await _accessControl.IsAdminAsync())
            {
                foreach (var subject in subjects)
                    subject.CurrentUserRole = AuthConstants.Admin;
            }
            else if (!string.IsNullOrEmpty(_currentUser.UserId))
            {
                var roles = await _context.SubjectMemberships
                    .Where(m => m.UserId == _currentUser.UserId)
                    .ToDictionaryAsync(m => m.SubjectId, m => m.RoleInSubject);
                foreach (var subject in subjects)
                    subject.CurrentUserRole = roles.GetValueOrDefault(subject.Id, string.Empty);
            }

            return subjects;
        }

        public async Task<SubjectDto?> GetByIdAsync(int id)
        {
            if (!await _accessControl.CanViewSubjectAsync(id))
                return null;

            var subject = await _context.Subjects.FindAsync(id);
            return subject?.ToDto(includeDocuments: false);
        }

        public async Task CreateAsync(SubjectInput input)
        {
            if (!await _accessControl.IsAdminAsync())
                throw new UnauthorizedAccessException("Only Admin can create subjects.");

            if (!await _subscriptionService.CanCreateSubjectAsync())
                throw new InvalidOperationException("Your subscription does not allow creating more subjects.");

            var organizationId = await GetCurrentOrganizationIdAsync();
            var normalizedCode = input.Code.Trim();
            var codeExists = await _context.Subjects.AnyAsync(s =>
                s.OrganizationId == organizationId &&
                s.Code.ToLower() == normalizedCode.ToLower());
            if (codeExists)
                throw new InvalidOperationException($"Subject code '{normalizedCode}' already exists in this organization.");

            var subject = new Subject
            {
                Name = input.Name.Trim(),
                Code = normalizedCode,
                OrganizationId = organizationId
            };
            _context.Subjects.Add(subject);
            await _context.SaveChangesAsync();

            await _auditLogService.RecordAsync("Create", "Subject", subject.Id, subject.Id, subject.OrganizationId, $"Created subject {subject.Name}.");
            await _realtime.SubjectChangedAsync("created", subject.Id, subject.Name);
        }

        public async Task<bool> UpdateAsync(SubjectInput input)
        {
            if (!await _accessControl.CanManageSubjectAsync(input.Id))
                return false;

            var subject = await _context.Subjects.FindAsync(input.Id);
            if (subject == null)
                return false;

            var normalizedCode = input.Code.Trim();
            var codeExists = await _context.Subjects.AnyAsync(s =>
                s.Id != input.Id &&
                s.OrganizationId == subject.OrganizationId &&
                s.Code.ToLower() == normalizedCode.ToLower());
            if (codeExists)
                return false;

            subject.Name = input.Name.Trim();
            subject.Code = normalizedCode;
            await _context.SaveChangesAsync();
            await _auditLogService.RecordAsync("Update", "Subject", subject.Id, subject.Id, subject.OrganizationId, $"Updated subject {subject.Name}.");
            await _realtime.SubjectChangedAsync("updated", subject.Id, subject.Name);
            return true;
        }

        public async Task<bool> DeleteAsync(int id)
        {
            if (!await _accessControl.IsAdminAsync())
                return false;

            var subject = await _context.Subjects
                .Include(s => s.Documents)
                .Include(s => s.ChatSessions!)
                    .ThenInclude(s => s.Messages)
                .FirstOrDefaultAsync(s => s.Id == id);

            if (subject == null)
                return false;

            var subjectName = subject.Name;
            var organizationId = subject.OrganizationId;
            var memberships = await _context.SubjectMemberships
                .Where(m => m.SubjectId == id)
                .ToListAsync();
            if (memberships.Any())
                _context.SubjectMemberships.RemoveRange(memberships);

            var sessions = subject.ChatSessions?.ToList() ?? new List<ChatSession>();
            var messages = sessions
                .SelectMany(s => s.Messages ?? new List<ChatMessage>())
                .ToList();
            if (messages.Any())
                _context.ChatMessages.RemoveRange(messages);

            if (sessions.Any())
                _context.ChatSessions.RemoveRange(sessions);

            var documents = subject.Documents?.ToList() ?? new List<Document>();
            if (documents.Any())
                _context.Documents.RemoveRange(documents);

            _context.Subjects.Remove(subject);
            await _context.SaveChangesAsync();
            await _auditLogService.RecordAsync("Delete", "Subject", id, id, organizationId, $"Deleted subject {subjectName}.");
            await _realtime.SubjectChangedAsync("deleted", id, subjectName);
            return true;
        }

        public Task<bool> ExistsAsync(int id)
        {
            return _context.Subjects.AnyAsync(s => s.Id == id);
        }

        private async Task<int?> GetCurrentOrganizationIdAsync()
        {
            var userId = _currentUser.UserId;
            if (string.IsNullOrEmpty(userId))
                return null;

            if (await _accessControl.IsAdminAsync())
            {
                return await _context.Organizations
                    .Where(o => o.IsActive)
                    .OrderBy(o => o.Id)
                    .Select(o => (int?)o.Id)
                    .FirstOrDefaultAsync();
            }

            return await _context.OrganizationMembers
                .Where(m => m.UserId == userId && m.Organization!.IsActive)
                .OrderBy(m => m.OrganizationId)
                .Select(m => (int?)m.OrganizationId)
                .FirstOrDefaultAsync();
        }
    }
}
