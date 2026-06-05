using System;
using System.Linq;
using System.Threading.Tasks;
using DataAccessLayer.Data;
using DataAccessLayer.Models;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using ServiceLayer.Models;

namespace ServiceLayer.Services
{
    public class AdminService : IAdminService
    {
        private readonly ApplicationDbContext _context;
        private readonly UserManager<ApplicationUser> _userManager;
        private readonly IAuditLogService _auditLogService;

        public AdminService(ApplicationDbContext context, UserManager<ApplicationUser> userManager, IAuditLogService auditLogService)
        {
            _context = context;
            _userManager = userManager;
            _auditLogService = auditLogService;
        }

        public async Task<AdminUserManagementDto> GetUsersAsync()
        {
            var users = await _userManager.Users.OrderBy(u => u.Email).ToListAsync();
            var result = new AdminUserManagementDto
            {
                Roles = new() { AuthConstants.Admin, AuthConstants.Lecturer, AuthConstants.Student }
            };

            foreach (var user in users)
            {
                var roles = await _userManager.GetRolesAsync(user);
                var organizationRole = await _context.OrganizationMembers
                    .Where(m => m.UserId == user.Id)
                    .OrderBy(m => m.OrganizationId)
                    .Select(m => m.RoleInOrganization)
                    .FirstOrDefaultAsync();

                result.Users.Add(new AdminUserDto
                {
                    UserId = user.Id,
                    Email = user.Email ?? "",
                    FullName = user.FullName,
                    Role = roles.FirstOrDefault() ?? AuthConstants.Student,
                    OrganizationRole = organizationRole ?? "Not joined"
                });
            }

            return result;
        }

        public async Task<AuthResult> CreateUserAsync(AdminCreateUserInput input)
        {
            var role = NormalizeRole(input.Role);
            if (string.IsNullOrWhiteSpace(input.Email) || string.IsNullOrWhiteSpace(input.Password))
                return new AuthResult { Success = false, Message = "Email and password are required." };

            var user = new ApplicationUser
            {
                UserName = input.Email.Trim(),
                Email = input.Email.Trim(),
                FullName = input.FullName.Trim(),
                EmailConfirmed = true
            };

            var result = await _userManager.CreateAsync(user, input.Password);
            if (!result.Succeeded)
            {
                return new AuthResult
                {
                    Success = false,
                    Message = "Could not create user.",
                    Errors = result.Errors.Select(e => e.Description).ToList()
                };
            }

            await _userManager.AddToRoleAsync(user, role);
            await EnsureOrganizationMembershipAsync(user.Id, role);
            await _context.SaveChangesAsync();
            await _auditLogService.RecordAsync("CreateUser", "Account", null, null, null, $"Created {role} account {user.Email}.");
            return new AuthResult { Success = true, Message = "User created." };
        }

        public async Task UpdateUserAsync(AdminEditUserInput input)
        {
            var user = await _userManager.FindByIdAsync(input.UserId);
            if (user == null)
                return;

            var role = NormalizeRole(input.Role);
            var currentRoles = await _userManager.GetRolesAsync(user);
            if (currentRoles.Any())
                await _userManager.RemoveFromRolesAsync(user, currentRoles);

            await _userManager.AddToRoleAsync(user, role);
            await EnsureOrganizationMembershipAsync(user.Id, role);
            await _context.SaveChangesAsync();
            await _auditLogService.RecordAsync("UpdateUserRole", "Account", null, null, null, $"Changed {user.Email} role to {role}.");
        }

        public async Task<AdminMembershipManagementDto> GetMembershipsAsync()
        {
            var users = await GetUsersAsync();
            var memberships = await _context.SubjectMemberships
                .Include(m => m.Subject)
                .Include(m => m.User)
                .OrderBy(m => m.Subject!.Name)
                .ThenBy(m => m.User!.Email)
                .Select(m => new SubjectMembershipAdminDto
                {
                    Id = m.Id,
                    SubjectId = m.SubjectId,
                    UserId = m.UserId,
                    SubjectName = m.Subject!.Name,
                    UserEmail = m.User!.Email ?? "",
                    RoleInSubject = m.RoleInSubject
                })
                .ToListAsync();

            foreach (var membership in memberships)
            {
                var user = await _userManager.FindByIdAsync(membership.UserId);
                membership.IsSystemAdmin = user != null && await _userManager.IsInRoleAsync(user, AuthConstants.Admin);
            }

            return new AdminMembershipManagementDto
            {
                Memberships = memberships,
                Subjects = await _context.Subjects.OrderBy(s => s.Name).Select(s => new AdminSubjectOptionDto { Id = s.Id, Name = s.Name }).ToListAsync(),
                Users = users.Users.Where(u => u.Role != AuthConstants.Admin).ToList()
            };
        }

        public async Task AddMembershipAsync(AdminMembershipInput input)
        {
            var exists = await _context.SubjectMemberships.AnyAsync(m => m.SubjectId == input.SubjectId && m.UserId == input.UserId);
            if (exists)
                return;

            _context.SubjectMemberships.Add(new SubjectMembership
            {
                SubjectId = input.SubjectId,
                UserId = input.UserId,
                RoleInSubject = input.RoleInSubject
            });
            await _context.SaveChangesAsync();
            await _auditLogService.RecordAsync("AddMember", "SubjectMembership", null, input.SubjectId, null, $"Admin added user to subject as {input.RoleInSubject}.");
        }

        public async Task RemoveMembershipAsync(int membershipId)
        {
            var membership = await _context.SubjectMemberships.FindAsync(membershipId);
            if (membership == null)
                return;

            _context.SubjectMemberships.Remove(membership);
            await _context.SaveChangesAsync();
            await _auditLogService.RecordAsync("RemoveMember", "SubjectMembership", membershipId, membership.SubjectId, null, "Admin removed a subject membership.");
        }

        private async Task EnsureOrganizationMembershipAsync(string userId, string role)
        {
            var organization = await _context.Organizations
                .Where(o => o.IsActive)
                .OrderBy(o => o.Id)
                .FirstOrDefaultAsync();
            if (organization == null)
                return;

            var membership = await _context.OrganizationMembers
                .FirstOrDefaultAsync(m => m.OrganizationId == organization.Id && m.UserId == userId);
            if (membership == null)
            {
                _context.OrganizationMembers.Add(new OrganizationMember
                {
                    OrganizationId = organization.Id,
                    UserId = userId,
                    RoleInOrganization = role,
                    JoinedAt = DateTime.UtcNow
                });
            }
            else
            {
                membership.RoleInOrganization = role;
            }
        }

        private static string NormalizeRole(string role)
        {
            return role == AuthConstants.Admin || role == AuthConstants.Lecturer || role == AuthConstants.Student
                ? role
                : AuthConstants.Student;
        }
    }
}
