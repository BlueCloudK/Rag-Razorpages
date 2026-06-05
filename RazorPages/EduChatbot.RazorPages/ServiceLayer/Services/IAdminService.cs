using System.Threading.Tasks;
using ServiceLayer.Models;

namespace ServiceLayer.Services
{
    public interface IAdminService
    {
        Task<AdminUserManagementDto> GetUsersAsync();
        Task<AuthResult> CreateUserAsync(AdminCreateUserInput input);
        Task UpdateUserAsync(AdminEditUserInput input);
        Task<AdminMembershipManagementDto> GetMembershipsAsync();
        Task AddMembershipAsync(AdminMembershipInput input);
        Task RemoveMembershipAsync(int membershipId);
    }
}
