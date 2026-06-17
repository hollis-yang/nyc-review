package com.baomidou.mybatisplus.extension.plugins.inner;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.core.toolkit.ParameterUtils;
import com.baomidou.mybatisplus.core.toolkit.PluginUtils;
import org.apache.ibatis.executor.Executor;
import org.apache.ibatis.mapping.BoundSql;
import org.apache.ibatis.mapping.MappedStatement;
import org.apache.ibatis.mapping.ParameterMapping;
import org.apache.ibatis.session.ResultHandler;
import org.apache.ibatis.session.RowBounds;

import java.sql.SQLException;
import java.util.List;
import java.util.Optional;

@SuppressWarnings({"rawtypes"})
public class PaginationInnerInterceptor implements InnerInterceptor {

    @Override
    public boolean willDoQuery(Executor executor, MappedStatement ms, Object parameter,
                               RowBounds rowBounds, ResultHandler resultHandler, BoundSql boundSql)
            throws SQLException {
        Optional<IPage> pageOpt = ParameterUtils.findPage(parameter);
        if (!pageOpt.isPresent()) {
            return true;
        }
        IPage page = pageOpt.get();
        String originalSql = boundSql.getSql().trim();
        long offset = page.offset();
        long limit = page.getSize();

        String pageSql = originalSql + " LIMIT " + limit + " OFFSET " + offset;
        PluginUtils.MPBoundSql mpBs = PluginUtils.mpBoundSql(boundSql);
        List<ParameterMapping> mappings = mpBs.parameterMappings();
        BoundSql newBoundSql = new BoundSql(
                ms.getConfiguration(), pageSql, mappings, parameter);
        PluginUtils.setAdditionalParameter(newBoundSql, mpBs.additionalParameters());
        mpBs.sql(pageSql);
        return true;
    }
}
