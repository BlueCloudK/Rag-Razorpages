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
    public class AuthService : IAuthService
    {
        private readonly ApplicationDbContext _context;
        private readonly SignInManager<ApplicationUser> _signInManager;
        private readonly UserManager<ApplicationUser> _userManager;
        private readonly IAuditLogService _auditLogService;

        public AuthService(ApplicationDbContext context, SignInManager<ApplicationUser> signInManager, UserManager<ApplicationUser> userManager, IAuditLogService auditLogService)
        {
            _context = context;
            _signInManager = signInManager;
            _userManager = userManager;
            _auditLogService = auditLogService;
        }

        public async Task<AuthResult> LoginAsync(LoginInput input)
        {
            var result = await _signInManager.PasswordSignInAsync(input.Email, input.Password, input.RememberMe, lockoutOnFailure: false);
            if (result.Succeeded)
            {
                var user = await _userManager.FindByEmailAsync(input.Email);
                var roles = user == null ? Array.Empty<string>() : await _userManager.GetRolesAsync(user);
                await _auditLogService.RecordForUserAsync(user?.Id, input.Email, roles.FirstOrDefault(), "Login", "Account", null, null, null, "User signed in.");
            }

            return new AuthResult
            {
                Success = result.Succeeded,
                Message = result.Succeeded ? "Logged in." : "Email or password is incorrect."
            };
        }

        public async Task<AuthResult> RegisterStudentAsync(RegisterInput input)
        {
            if (input.Password != input.ConfirmPassword)
                return new AuthResult { Success = false, Message = "Password confirmation does not match." };

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
                    Message = "Could not create account.",
                    Errors = result.Errors.Select(e => e.Description).ToList()
                };
            }

            await _userManager.AddToRoleAsync(user, AuthConstants.Student);
            await EnsureDefaultOrganizationMembershipAsync(user.Id, AuthConstants.Student);
            await _auditLogService.RecordForUserAsync(user.Id, user.Email ?? user.UserName ?? "", AuthConstants.Student, "Register", "Account", null, null, null, "Student account created.");
            await _signInManager.SignInAsync(user, isPersistent: false);
            return new AuthResult { Success = true, Message = "Account created." };
        }

        public Task LogoutAsync()
        {
            return _signInManager.SignOutAsync();
        }

        private async Task EnsureDefaultOrganizationMembershipAsync(string userId, string role)
        {
            var organization = await _context.Organizations.OrderBy(o => o.Id).FirstOrDefaultAsync(o => o.IsActive);
            if (organization == null)
                return;

            var exists = await _context.OrganizationMembers.AnyAsync(m => m.OrganizationId == organization.Id && m.UserId == userId);
            if (exists)
                return;

            _context.OrganizationMembers.Add(new OrganizationMember
            {
                OrganizationId = organization.Id,
                UserId = userId,
                RoleInOrganization = role
            });
            await _context.SaveChangesAsync();
        }
    }
}
