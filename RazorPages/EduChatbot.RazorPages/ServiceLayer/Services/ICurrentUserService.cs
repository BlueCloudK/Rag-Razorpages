using System.Threading.Tasks;
using DataAccessLayer.Models;

namespace ServiceLayer.Services
{
    public interface ICurrentUserService
    {
        string? UserId { get; }
        bool IsAuthenticated { get; }
        Task<ApplicationUser?> GetCurrentUserAsync();
        Task<bool> IsInRoleAsync(string role);
    }
}
