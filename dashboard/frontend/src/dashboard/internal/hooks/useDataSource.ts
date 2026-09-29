import { useCallback, useEffect, useState } from 'react'
import { getDataSource, onDataSourceChange, setDataSource } from '../client'
import type { DataSource } from '../client'

/** 헤더 토글이 쓰는 훅. 전환은 전역이므로 어느 컴포넌트에서 바꿔도 모두가 같은 값을 본다. */
export function useDataSource() {
  const [source, setSource] = useState<DataSource>(getDataSource)

  useEffect(() => onDataSourceChange(setSource), [])

  const toggle = useCallback(() => {
    setDataSource(getDataSource() === 'mock' ? 'live' : 'mock')
  }, [])

  return { source, isMock: source === 'mock', setSource: setDataSource, toggle }
}
