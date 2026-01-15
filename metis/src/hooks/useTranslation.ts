import { useIntl } from 'react-intl';

export function useTranslation() {
  const intl = useIntl();

  const t = (key: string, values?: Record<string, any>) => {
    return intl.formatMessage({ id: key }, values);
  };

  return { t };
}
