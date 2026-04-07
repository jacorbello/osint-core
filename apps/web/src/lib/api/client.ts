import axios from 'axios';

export const apiClient = axios.create({
  baseURL: 'https://osint.corbello.io',
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000,
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.data) {
      const problemDetails = error.response.data;
      if (problemDetails.type && problemDetails.title && problemDetails.status) {
        return Promise.reject(problemDetails);
      }
    }
    return Promise.reject(error);
  }
);
