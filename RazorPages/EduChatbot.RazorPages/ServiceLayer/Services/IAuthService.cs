using System.Threading.Tasks;
using ServiceLayer.Models;

namespace ServiceLayer.Services
{
    public interface IAuthService
    {
        Task<AuthResult> LoginAsync(LoginInput input);
        Task<AuthResult> RegisterStudentAsync(RegisterInput input);
        Task LogoutAsync();
    }
}
