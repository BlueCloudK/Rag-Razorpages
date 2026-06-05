using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using DataAccessLayer.Data;
using Microsoft.EntityFrameworkCore;
using ServiceLayer.Models;

namespace ServiceLayer.Services
{
    public class OrganizationService : IOrganizationService
    {
        private readonly ApplicationDbContext _context;
        private readonly ICurrentUserService _currentUser;
        private readonly IAccessControlService _accessControl;
        private readonly ISubscriptionService _subscriptionService;

        public OrganizationService(
            ApplicationDbContext context,
            ICurrentUserService currentUser,
            IAccessControlService accessControl,
            ISubscriptionService subscriptionService)
        {
            _context = context;
            _currentUser = currentUser;
            _accessControl = accessControl;
            _subscriptionService = subscriptionService;
        }

        public async Task<OrganizationDto?> GetCurrentOrganizationAsync()
        {
            var userId = _currentUser.UserId;
            if (string.IsNullOrEmpty(userId))
                return null;

            if (await _accessControl.IsAdminAsync())
            {
                return await _context.Organizations
                    .Where(o => o.IsActive)
                    .OrderBy(o => o.Id)
                    .Select(o => new OrganizationDto
                    {
                        Id = o.Id,
                        Name = o.Name,
                        Slug = o.Slug,
                        RoleInOrganization = AuthConstants.Admin
                    })
                    .FirstOrDefaultAsync();
            }

            return await _context.OrganizationMembers
                .Include(m => m.Organization)
                .Where(m => m.UserId == userId && m.Organization!.IsActive)
                .OrderBy(m => m.OrganizationId)
                .Select(m => new OrganizationDto
                {
                    Id = m.OrganizationId,
                    Name = m.Organization!.Name,
                    Slug = m.Organization.Slug,
                    RoleInOrganization = m.RoleInOrganization
                })
                .FirstOrDefaultAsync();
        }

        public async Task<int?> GetCurrentOrganizationIdAsync()
        {
            return (await GetCurrentOrganizationAsync())?.Id;
        }

        public async Task<bool> CanManageCurrentOrganizationAsync()
        {
            if (await _accessControl.IsAdminAsync())
                return true;

            var org = await GetCurrentOrganizationAsync();
            return org != null && (org.RoleInOrganization == AuthConstants.Lecturer || org.RoleInOrganization == AuthConstants.Admin);
        }

        public async Task<OrganizationDashboardDto> GetDashboardAsync()
        {
            var org = await GetCurrentOrganizationAsync();
            var canManage = await CanManageCurrentOrganizationAsync();
            var subjects = await BuildSubjectQuery(org?.Id)
                .Include(s => s.Documents)
                .OrderBy(s => s.Name)
                .ToListAsync();

            var documents = await _context.Documents
                .Include(d => d.Subject)
                .Where(d => org == null || d.Subject!.OrganizationId == org.Id)
                .OrderByDescending(d => d.UploadedAt)
                .Take(6)
                .ToListAsync();

            return new OrganizationDashboardDto
            {
                Organization = org,
                Subscription = await _subscriptionService.GetCurrentStatusAsync(),
                Subjects = subjects.Select(s => s.ToDto(includeDocuments: true)).ToList(),
                RecentDocuments = documents.Select(d => d.ToDto()).ToList(),
                MemberCount = org == null ? 0 : await _context.OrganizationMembers.CountAsync(m => m.OrganizationId == org.Id),
                IndexedDocumentCount = documents.Count(d => d.IsIndexed),
                ProcessingDocumentCount = await _context.Documents.CountAsync(d => (org == null || d.Subject!.OrganizationId == org.Id) && !d.IsIndexed && d.IndexStatus != "Failed"),
                CanManageOrganization = canManage,
                CanCreateSubject = canManage && await _subscriptionService.CanCreateSubjectAsync()
            };
        }

        public async Task<List<OrganizationMemberDto>> GetMembersAsync()
        {
            var org = await GetCurrentOrganizationAsync();
            if (org == null)
                return new List<OrganizationMemberDto>();

            return await _context.OrganizationMembers
                .Include(m => m.User)
                .Where(m => m.OrganizationId == org.Id)
                .OrderBy(m => m.User!.Email)
                .Select(m => new OrganizationMemberDto
                {
                    Id = m.Id,
                    Email = m.User!.Email ?? "",
                    FullName = m.User.FullName,
                    RoleInOrganization = m.RoleInOrganization,
                    JoinedAt = m.JoinedAt
                })
                .ToListAsync();
        }

        private IQueryable<DataAccessLayer.Models.Subject> BuildSubjectQuery(int? organizationId)
        {
            var query = _context.Subjects.AsQueryable();
            if (organizationId.HasValue)
                query = query.Where(s => s.OrganizationId == organizationId.Value);
            return query;
        }
    }
}
