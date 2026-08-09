export function normalizePdfPageNumber(pageNumber) {
  const parsed = Number.parseInt(String(pageNumber ?? ''), 10);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 1;
}

export function buildPdfPreviewUrl(objectUrl, pageNumber) {
  return `${objectUrl}#page=${normalizePdfPageNumber(pageNumber)}&view=FitH`;
}

export function getPreviewErrorMessage(error) {
  if (error?.status === 415) {
    return 'Định dạng tài liệu này hiện chưa hỗ trợ xem trước.';
  }
  if (error?.status === 404) {
    return 'Không tìm thấy tài liệu gốc hoặc bạn không còn quyền truy cập.';
  }
  return 'Không thể tải bản xem trước tài liệu. Vui lòng thử lại sau.';
}
