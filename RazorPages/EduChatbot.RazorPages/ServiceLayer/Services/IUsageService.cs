using System.Threading.Tasks;

namespace ServiceLayer.Services
{
    public interface IUsageService
    {
        Task<int> GetTodayQuestionCountAsync();
        Task IncrementQuestionCountAsync();
    }
}
